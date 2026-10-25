import math
import random
import time
import tkinter as tk


ANCHO, ALTO = 960, 440
PISO = 390
CASTILLO_X = 80
ARQUERO_X, ARQUERO_Y = 58, PISO - 155
GRAVEDAD = 0.25
VIDAS = 5
V_MIN, V_MAX = 5.0, 17.5
ANG_MIN, ANG_MAX = -85.0, 75.0
MAX_DURACION_GENERACION = 60 * 75
COOLDOWN = 30       # Frames de espera para disparo de flechas
TIEMPO_CARGA = 1.2   # Tiempo en segundos que se puede mantener presionado para cargar el disparo

TIPOS_ENEMIGOS = {
    "soldado": dict( vel=1.0, radio=14, vuela=False, color="red", w=4), #W sería el weight, o sea la chance de que salga ese enemigo
    "corredor": dict( vel=2.1, radio=10, vuela=False, color="blue", w=2),
    "tanque": dict( vel=0.55, radio=21, vuela=False, color="green", w=2),
    "murcielago": dict( vel=1.5, radio=11, vuela=True, color="yellow", w=2),
}

TIPOS = list(TIPOS_ENEMIGOS)
PESO_TIPOS = [TIPOS_ENEMIGOS[k]["w"] for k in TIPOS] 


class Enemigo:
    def __init__(self, tipo, rng):
        t = TIPOS_ENEMIGOS[tipo]
        self.tipo = tipo
        self.r = t["radio"]
        self.vuela = t["vuela"]
        self.vel = t["vel"] * rng.uniform (0.85, 1.15)
        self.x = ANCHO + 20
        self.base_y =  PISO - 120 - rng.uniform(0,90) if self.vuela else PISO - self.r #Si vuela le damos una altura aleatoria, si no, al suelo
        self.y = self.base_y
        self.phase = rng.uniform (0, 6.28) #Esto indica la posicion inicial del movimiento senoidal, los voladores hacen un movimiento senoidal, suben y bajan     
        self.vivo = True

    def actualizar(self, frame_juego):#frame_juego es para que todos los enemigos se muevan al mismo ritmo
        self.x -= self.vel #se acerca a nuestro cero, o sea, nuestro castillo
        if self.vuela:                
            self.y = self.base_y + math.sin(frame_juego *0.07 + self.phase) * 22 #Esto indica un movimiento senoidal en el eje y

class Flecha:
    def __init__(self, x, y, potencia, angulo_grados):
        self.x = x
        self.y = y
        rad = math.radians(angulo_grados)
        self.vx = potencia * math.cos(rad)
        self.vy = -potencia * math.sin(rad) #de angulos a radianes y hacemos trigonometria para sacar las velocidades
        self.activa = True

    def actualizar(self):
        if not self.activa:
            return
        self.vy += GRAVEDAD
        self.x += self.vx
        self.y += self.vy
        if self.y >= PISO:
            self.y = PISO
            self.activa = False
        elif self.x > ANCHO + 50 or self.x < -50:
            self.activa = False #si toca el piso o sale de la pantalla se desactiva


class Juego:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.enemigos = []
        self.flechas = []
        self.vidas = VIDAS
        self.bajas = 0
        self.tiempo = 0
        self.spawn_timer = 60
        self.cool=0

    def spawn(self):
        self.spawn_timer -= 1
        if self.spawn_timer > 0:
            return
        diff = min(1.0, self.tiempo / (60 * 60)) # dificultad sube durante 60 seg
        tipo = self.rng.choices(TIPOS, weights=PESO_TIPOS)[0]
        e = Enemigo(tipo, self.rng)
        e.vel *= 1 + 0.5 * diff #La velocidad aumenta con la dificultad
        self.enemigos.append(e)
        self.spawn_timer = int(self.rng.uniform(90, 150) * (1 - 0.5 * diff))

    def disparar(self, potencia_normalizada, angulo_grados):
        if self.vidas <= 0 or self.cool >0:
            return False
        potencia = V_MIN+(V_MAX-V_MIN) * max (0.0, min (1.0, potencia_normalizada))
        nueva_flecha = Flecha(ARQUERO_X, ARQUERO_Y, potencia, angulo_grados)
        self.flechas.append(nueva_flecha)
        self.cool = COOLDOWN
        return True

    def actualizar(self):
        if self.vidas <= 0:
            return
        self.tiempo += 1
        if self.cool > 0:
            self.cool -= 1
        self.spawn()
        for enemigo in self.enemigos:
            enemigo.actualizar(self.tiempo)
            if enemigo.x - enemigo.r <= CASTILLO_X:
                self.vidas -= 1
                enemigo.vivo = False #El enemigo al tocar el castillo se borra y quita una vida
        for flecha in self.flechas:
            if not flecha.activa:
                continue
            flecha.actualizar()
            #Chequeo colision con enemigos
            for enemigo in self.enemigos:
                if not enemigo.vivo:
                    continue #Si no hay enemigos vivos, no tiene sentido chequear colision
                dx = enemigo.x - flecha.x
                dy = enemigo.y - flecha.y
                if dx * dx + dy * dy <= (enemigo.r + 4) ** 2: #Este calculo es para saber si la flecha colisiona con el enemigo
                    enemigo.vivo = False #La flecha colisiona con el enemigo, ambos se desactivan y aumenta la cuenta de bajas
                    flecha.activa = False
                    self.bajas += 1
                    break
        
        self.enemigos = [e for e in self.enemigos if e.vivo]
        self.flechas = [f for f in self.flechas if f.activa] 

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Arquerito Inteligente TD")
        self.root.configure(bg="#12131f") # Color de fondo de la ventana (azul oscuro)
        root.resizable(False, False)     # Evita que el usuario deforme las dimensiones del juego
        self.juego = Juego()             # Instancia de la lógica del juego

        # Lienzo principal (Canvas)
        self.canvas = tk.Canvas(root, width=ANCHO, height=ALTO, bg="#0f1028", highlightthickness=0)
        self.canvas.pack(padx=10, pady=10) # Margen de separación exterior

        # Dibujamos el escenario estático (solo una vez, de fondo)
        self.dibujar_escenario()

        self.mouse= (ANCHO/2,ALTO/2)
        self.tiempo_presionado= None
        self.angulo_apuntado=20.0

        self.canvas.bind("<Motion>", self.al_mover_mouse)
        self.canvas.bind("<B1-Motion>", self.al_mover_mouse)
        self.canvas.bind("<ButtonPress-1>", self.al_presionar_mouse)
        self.root.bind("<ButtonRelease-1>", self.al_soltar_mouse)
        self.root.bind("<KeyPress-r>", lambda e: self.reiniciar())
        self.root.bind("<KeyPress-R>", lambda e: self.reiniciar())

        self.loop()                      # Arrancamos el bucle una vez que todo está listo
        
    def al_mover_mouse(self, ev):
        self.mouse = (ev.x, ev.y)

    def al_presionar_mouse(self, ev):
        if self.juego.vidas > 0:
            self.tiempo_presionado = time.time()

    def al_soltar_mouse(self, ev):
        if self.tiempo_presionado is None:
            return
        self.juego.disparar(self.calcular_potencia(), self.calcular_angulo())
        self.tiempo_presionado = None
    
    def calcular_potencia(self):
        if self.tiempo_presionado is None:
            return 0.0
        return min(1.0, (time.time() - self.tiempo_presionado) / TIEMPO_CARGA)
    
    def calcular_angulo(self):
        mx, my = self.mouse
        ang = math.degrees(math.atan2(ARQUERO_Y - my, max(1.0, mx - ARQUERO_X)))
        return max(ANG_MIN, min(ANG_MAX, ang))
    
    def reiniciar(self):
        self.juego = Juego()          # Crea una instancia nueva del juego
        self.tiempo_presionado = None # Resetea la carga
        
    def loop(self):
        self.juego.actualizar()          # Avanza enemigos, flechas y colisiones
        self.dibujar_entidades()         # Redibuja arquero, enemigos y flechas
        self.root.after(16, self.loop)    # Se vuelve a llamar en 16 milisegundos (1000/60 ~= 16ms)

    def dibujar_entidades(self):
        c = self.canvas
        T = "dyn"     # Etiqueta que indica que un elemento se mueve y hay que redibujarlo
        c.delete(T)   # Borra los elementos móviles de los frames anteriores

        self.angulo_apuntado = self.calcular_angulo()
        ang = self.angulo_apuntado
        rad = math.radians(ang)

        # Línea punteada de apuntado
        p = self.calcular_potencia()
        L = 30 + 90 * p
        c.create_line(ARQUERO_X, ARQUERO_Y, ARQUERO_X + L * math.cos(rad), ARQUERO_Y - L * math.sin(rad),
                      dash=(4, 4), fill="#ffffff" if self.tiempo_presionado else "#777777", tags=T)

        # Barra de carga de potencia
        bx, by = 10, PISO - 228
        c.create_rectangle(bx, by, bx + 72, by + 10, outline="#e8e6f0", tags=T)
        if p > 0:
            c.create_rectangle(bx + 1, by + 1, bx + 1 + 70 * p, by + 9, fill="#f4a261", outline="", tags=T)

        # Cartel de GAME OVER si te quedas sin vidas
        if self.juego.vidas <= 0:
            c.create_rectangle(0, 0, ANCHO, ALTO, fill="#000000", stipple="gray50", outline="", tags=T)
            c.create_text(ANCHO / 2, ALTO / 2 - 18, text="GAME OVER", fill="#f4a261", font=("Segoe UI", 34, "bold"), tags=T)
            c.create_text(ANCHO / 2, ALTO / 2 + 22, text="Pulsa R para reiniciar", fill="#e8e6f0", font=("Segoe UI", 12), tags=T)

        ax=ARQUERO_X -9
        c.create_line(ax,PISO-145, ax, PISO-162,fill="#2b2d42", width=5, tags=T) #Cuerpo
        c.create_oval(ax-5, PISO -173, ax+5, PISO-163,fill="#f1c27d",outline="",tags=T) #Cabeza
        c.create_arc(ax-6, PISO-176, ax+6, PISO-164, start=0, extent=180, fill="#2d6a4f", outline="", tags=T) #GORRO
        c.create_line(ax,PISO-157,ARQUERO_X,ARQUERO_Y,fill="#2b2d42",width=3,tags=T)#BRAZO

        #Para el arco es más complejo porque se mueve e inclina
        R = 15
        ang = self.angulo_apuntado
        c.create_arc(ARQUERO_X-R, ARQUERO_Y-R, ARQUERO_X+R, ARQUERO_Y+R, start=ang-75, extent=150, style="arc", outline="#d4a373", width=3, tags=T)

        #Enemigos
        for e in self.juego.enemigos:
            self.dibujar_enemigo(e,self.juego.tiempo,T)
        #FLECHAS
        for f in self.juego.flechas:
                th=math.atan2(f.vy,f.vx)
                c.create_line(f.x - math.cos(th)*20, f.y - math.sin(th)*20,f.x,f.y,fill="#f4e9cd",width=2,arrow=tk.LAST, arrowshape=(7,8,3), tags=T)

        #HUD
        c.create_text(20,20,anchor="nw",text=f"VIDAS:{self.juego.vidas} | BAJAS: {self.juego.bajas}",fill="#e8e6f0", font=("Segoe UI",12, "bold"), tags=T) 
    def dibujar_enemigo(self,e,frame,T):
        c = self.canvas
        x,y,r = e.x, e.y, e.r
        col= TIPOS_ENEMIGOS[e.tipo]["color"]
        #Sombra del suelo
        c.create_oval(x-r,PISO-3, x+r ,PISO+3,fill="#16241a",outline="",tags=T)
        if e.tipo == "soldado":
            bob = abs(math.sin(frame * 0.2 + e.phase)) * 2  # Vaivén al caminar
            c.create_line(x - 9, y - 20 - bob, x - 9, y + r, fill="#c9c9c9", width=2, tags=T)  # Lanza
            c.create_rectangle(x - 6, y - 5 - bob, x + 6, y + r, fill=col, outline="", tags=T)  # Torso rojo
            c.create_oval(x - 5, y - 15 - bob, x + 5, y - 5 - bob, fill="#f1c27d", outline="", tags=T)  # Cabeza
        elif e.tipo == "corredor":
            # Polígono aerodinámico azul
            c.create_polygon(x - r, y, x + r, y - r, x + r * 0.6, y, x + r, y + r,
                             fill=col, outline="", tags=T)
        elif e.tipo == "tanque":
            # Bloque blindado verde
            c.create_rectangle(x - r, y - r, x + r, y + r, fill=col, outline="", width=2, tags=T)
            c.create_rectangle(x - r + 5, y - r + 5, x + r - 5, y + r - 7, fill="#2b2d42", outline="", tags=T)
        elif e.tipo == "murcielago":
            # Alas que aletean usando el seno
            aleteo = math.sin(frame * 0.4 + e.phase) * r
            for lado in (-1, 1):
                c.create_polygon(x + 2 * lado, y, x + r * 1.7 * lado, y - aleteo, x + r * 0.7 * lado, y + 3,
                                 fill="#5c4d28", outline=col, tags=T)
            c.create_oval(x - 6, y - 6, x + 6, y + 6, fill=col, outline="", tags=T)  # Cuerpo amarillo



    def dibujar_escenario(self):
        c = self.canvas
        """
        create_rectangle(x1, y1, x2, y2, **options):
          (x1, y1) = esquina superior izquierda
          (x2, y2) = esquina inferior derecha
        """
        # 1. CIELO (cubre desde y=0 hasta el piso)
        c.create_rectangle(0, 0, ANCHO, PISO, fill="#161838", outline="")

        # 2. PASTO
        c.create_rectangle(0, PISO, ANCHO, ALTO, fill="#263d2a", outline="")

        # 3. LÍNEA DEL SUELO (da relieve y color al césped)
        c.create_line(0, PISO, ANCHO, PISO, fill="#5b8c3e", width=3)

        # 4. LUNA
        c.create_oval(820, 40, 868, 88, fill="#f6e7c1", outline="")

        # 5. CASTILLO MEDIEVAL
        stone, dark = "#6b6f80", "#3b3e4a" # Colores de piedra gris y borde oscuro

        # Base principal del muro 
        c.create_rectangle(6, PISO - 100, CASTILLO_X, PISO, fill=stone, outline=dark, width=2)

        # Almenas de la muralla baja
        for x in range(6, CASTILLO_X, 16):
            c.create_rectangle(x, PISO - 110, x + 9, PISO - 100, fill=stone, outline=dark)

        # Torre superior 
        c.create_rectangle(26, PISO - 145, 74, PISO - 100, fill="#777b8e", outline=dark, width=2)

        # Almenas de la torre superior
        for x in range(26, 74, 13):
            c.create_rectangle(x, PISO - 152, x + 7, PISO - 145, fill="#777b8e", outline=dark)

        # Ventana de vigía en la torre
        c.create_rectangle(44, PISO - 132, 52, PISO - 116, fill="#1b1d2e", outline="")

        # Puerta de madera en la base
        c.create_rectangle(30, PISO - 40, 56, PISO, fill="#4a3426", outline=dark)
        c.create_arc(30, PISO - 53, 56, PISO - 27, start=0, extent=180, fill="#4a3426", outline=dark)

        # Mástil de la bandera
        c.create_line(68, PISO - 152, 68, PISO - 195, fill="#cfcfcf", width=2)

        # Bandera ondeando 
        c.create_polygon(68, PISO - 195, 92, PISO - 187, 68, PISO - 179, fill="#f4a261", outline="")


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()


