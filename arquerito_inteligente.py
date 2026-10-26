import math
import random
import time
import tkinter as tk

#Paleta de colores de la interfaz
BG_UI = "#12131f"
PANEL = "#1b1d2e"
TEXTO = "#e8e6f0"
MUTED = "#8b8aa6"
ACENTO = "#f4a261"
ACENTO2 = "#4cc9f0"

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
FRAMES_TENSADO = 12 # Frames fijos de tensado del arco (animación de cuerda y flecha)
TIEMPO_CARGA = 1.2   # Tiempo en segundos que se puede mantener presionado para cargar el disparo

TIPOS_ENEMIGOS = {
    "soldado": dict( vel=1.0, radio=14, vuela=False, color="red", w=4), #W sería el weight, o sea la chance de que salga ese enemigo
    "corredor": dict( vel=2.1, radio=10, vuela=False, color="blue", w=2),
    "tanque": dict( vel=0.55, radio=21, vuela=False, color="green", w=2),
    "murcielago": dict( vel=1.5, radio=11, vuela=True, color="yellow", w=2),
}

TIPOS = list(TIPOS_ENEMIGOS)
PESO_TIPOS = [TIPOS_ENEMIGOS[k]["w"] for k in TIPOS] 


#Configuración neuronal:
SENSORES_ENTRADA = 7 #7 sensores de entrada, lo que nos interesa que considere la red
SENSORES_OCULTA = 12 #Aumentado de 8 a 12 para facilitar el cálculo balístico de objetivos rápidos (corredores)
NEURONAS_SALIDA = 2 #La idea es que la ia decida con que angulo disparar y con qué potencia

POBLACION = 100 #Comenzamos con 100 arqueros que nos interesa que mejoren con cada generación
ELITE = 10 #Los 10 mejores son los que pasan con sus pesos intactos a la siguiente generación, el resto se les cambia
MUTACION = 0.10 #Probabilidad del 10% de que muten los pesos
MUTACION_SIGMAS=(0.03,0.1,0.3) #Desviaciones estándar para la mutación, 3 niveles, baja, media y alta

#https://en.wikipedia.org/wiki/Sigmoid_function
def sigmoid(x): #Es la función de activación
    if x<-60:
        return 0.0
    return 1.0/ (1.0 + math.exp(-x)) #Valor entre 0 y 1


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
    def __init__(self, x, y, potencia, angulo_grados, objetivo=None): #Agregamos un objetivo, es para la red neuronal para que sepa que falló o acertó
        self.x = x
        self.y = y
        rad = math.radians(angulo_grados)
        self.vx = potencia * math.cos(rad)
        self.vy = -potencia * math.sin(rad) # de ángulos a radianes y hacemos trigonometría para sacar las velocidades
        self.activa = True
        self.objetivo = objetivo
        self.mejor_distancia = 9999.0 #Distancia mini registrada, menos es mejor

    def actualizar(self):
        if not self.activa:
            return
        self.vy += GRAVEDAD
        self.x += self.vx
        self.y += self.vy
        if self.objetivo is not None and self.objetivo.vivo:
            d = math.hypot(self.objetivo.x - self.x, self.objetivo.y - self.y)
            if d < self.mejor_distancia:
                self.mejor_distancia = d
        if self.y >= PISO:
            self.y = PISO
            self.activa = False
        elif self.x > ANCHO + 50 or self.x < -50:
            self.activa = False # si toca el piso o sale de la pantalla se desactiva
class Cerebro:
    N1 = SENSORES_OCULTA * (SENSORES_ENTRADA + 1)  # El umbral (bias) nos suma 1
    N2 = NEURONAS_SALIDA * (SENSORES_OCULTA + 1)   # También hay umbral de la capa oculta a la salida

    def __init__(self, genes=None):
        if genes is not None:
            self.genes = genes
        else: 
            self.genes = [random.uniform(-1, 1) for _ in range(self.N1 + self.N2)] # Generamos los pesos con números aleatorios

        # Guardamos activaciones para tenerlas para dibujar
        self.entrada = [0.0] * SENSORES_ENTRADA
        self.oculta = [0.0] * SENSORES_OCULTA
        self.salida = [0.5] * NEURONAS_SALIDA

    def w_ih(self, i, j):
        # Entrada i a oculta j, si i == SENSORES_ENTRADA es el umbral
        return self.genes[j * (SENSORES_ENTRADA + 1) + i]

    def w_ho(self, j, k):
        return self.genes[self.N1 + k * (SENSORES_OCULTA + 1) + j]

    def forward(self, x):
        g = self.genes
        oculta = []
        for j in range(SENSORES_OCULTA):
            base = j * (SENSORES_ENTRADA + 1)
            suma = g[base + SENSORES_ENTRADA]
            for i in range(SENSORES_ENTRADA):
                suma += g[base + i] * x[i] # Multiplicamos cada peso por cada entrada
            oculta.append(math.tanh(suma)) # Tanh entrega entre -1 y 1 (dentro del bucle)

        salida = []
        for k in range(NEURONAS_SALIDA):
            base = self.N1 + k * (SENSORES_OCULTA + 1)
            suma = g[base + SENSORES_OCULTA]
            for j in range(SENSORES_OCULTA):
                suma += g[base + j] * oculta[j]
            salida.append(sigmoid(suma)) # Salida entre 0 y 1 de la función sigmoide

        self.entrada, self.oculta, self.salida = list(x), oculta, salida
        return salida # Potencia_01 y Angulo_01

    def clonar(self):
        return Cerebro(self.genes[:])

    @staticmethod
    def cruzar(a, b):
        # Combina los genes de dos arqueros padres
        return Cerebro([ga if random.random() < 0.5 else gb for ga, gb in zip(a.genes, b.genes)])

    def mutar(self, rate, sigma):
        # Aplica las mutaciones a los pesos
        g = self.genes 
        for i in range(len(g)):
            if random.random() < rate:
                if random.random() < 0.1:
                    # 10% chance de reinicio completo del peso (exploración radical)
                    g[i] = random.uniform(-1, 1)
                else:
                    # 90% chance de ajuste fino con distribución gaussiana
                    g[i] = max(-4.0, min(4.0, g[i] + random.gauss(0, sigma)))
class Juego:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.enemigos = []
        self.flechas = []
        self.vidas = VIDAS
        self.bajas = 0
        self.tiempo = 0
        self.spawn_timer = 60
        self.cool = 0
        self.shaping = 0.0 # Puntos por tiros cercanos, es para premiar
        self.terminado = False # Si termina el run de la ia

        # Simulación de tensión y carga del arco (tiempo que el arquero mantiene la cuerda estirada)
        self.cargando = False
        self.carga_potencia = 0.0
        self.carga_angulo = 0.0
        self.frames_carga = 0
        self.frames_carga_total = 0

    def preparar_disparo(self, potencia_normalizada, angulo_grados):
        # La IA tensa el arco; el tiempo de tensado es constante (FRAMES_TENSADO)
        # para no penalizar con retraso los disparos de máxima potencia
        if self.vidas <= 0 or self.cool > 0 or self.cargando:
            return False
        self.cargando = True
        self.carga_potencia = max(0.1, min(1.0, potencia_normalizada))
        self.carga_angulo = angulo_grados
        self.frames_carga_total = FRAMES_TENSADO
        self.frames_carga = FRAMES_TENSADO
        return True

    def potencia_actual(self):
        # Retorna el porcentaje actual de tensión (0.0 a 1.0) para la animación visual
        if not self.cargando or self.frames_carga_total <= 0:
            return 0.0
        progreso = 1.0 - (self.frames_carga / self.frames_carga_total)
        return self.carga_potencia * progreso

    def _recompensar_tiro_cercano(self, flecha):
        # Si pasa a menos de 150px, nos da puntos proporcionales a la cercanía
        if flecha.mejor_distancia < 150.0:
            # Bonus adicional de aprendizaje si el objetivo era un corredor veloz
            factor = 1.8 if (flecha.objetivo and flecha.objetivo.tipo == "corredor") else 1.0
            self.shaping += max(0.0, 1.0 - flecha.mejor_distancia / 150.0) * 4.0 * factor    
    
    def sensores(self): 
        #Se normalizan los 7 valores que buscamos, se toman valores de 0 a 1 para que ninguno predomine sobre el otro
        cercanos = sorted(self.enemigos, key=lambda e: e.x)[:2] #tomamos los dos más cercanos
        datos= []
        for i in range(2):
            if i < len(cercanos):
                e=cercanos[i]
                distancia= (e.x - CASTILLO_X)/(ANCHO-CASTILLO_X)
                altura=(PISO-e.y)/200
                velocidad= e.vel/4.0
                datos.extend([distancia,altura,velocidad])
            else:
                datos.extend([1.0,0.0,0.0]) #No hay enemigos o solo hay uno
        cantidad_normalizada = min(len(self.enemigos),10)/10.0 #Cantidad normalizada de cantidad de enemigos
        datos.append(cantidad_normalizada)
        return datos

    def spawn(self):
        self.spawn_timer -= 1
        if self.spawn_timer > 0:
            return
        diff = min(1.0, self.tiempo / (60 * 60)) # La dificultad sube durante 60 seg
        tipo = self.rng.choices(TIPOS, weights=PESO_TIPOS)[0]
        e = Enemigo(tipo, self.rng)
        e.vel *= 1 + 0.5 * diff # La velocidad aumenta con la dificultad
        self.enemigos.append(e)
        self.spawn_timer = int(self.rng.uniform(90, 150) * (1 - 0.5 * diff))

    def disparar(self, potencia_normalizada, angulo_grados, cool=COOLDOWN):
        if self.vidas <= 0 or self.cool > 0:
            return False
        potencia = V_MIN + (V_MAX - V_MIN) * max(0.0, min(1.0, potencia_normalizada))
        objetivo = min(self.enemigos, key=lambda e: e.x) if self.enemigos else None # Toma el más cercano
        nueva_flecha = Flecha(ARQUERO_X, ARQUERO_Y, potencia, angulo_grados, objetivo)
        self.flechas.append(nueva_flecha)
        self.cool = cool
        return True
    
    def fitness(self):
        vidas_perdidas = VIDAS - self.vidas
        return self.bajas*10+self.shaping - vidas_perdidas* 8 +(self.tiempo/60)*1.0 

    def actualizar(self):
        if self.vidas <= 0 or self.tiempo>= MAX_DURACION_GENERACION: 
            self.terminado = True
            return
        self.tiempo += 1
        if self.cool > 0:
            self.cool -= 1

        # Procesa la tensión del arco si se está preparando un disparo
        if self.cargando:
            self.frames_carga -= 1
            if self.frames_carga <= 0:
                self.cargando = False
                self.disparar(self.carga_potencia, self.carga_angulo, cool=max(1, COOLDOWN - FRAMES_TENSADO))

        self.spawn()

        for enemigo in self.enemigos:
            enemigo.actualizar(self.tiempo)
            if enemigo.x - enemigo.r <= CASTILLO_X:
                self.vidas -= 1
                enemigo.vivo = False # El enemigo al tocar el castillo se borra y quita una vida

        for flecha in self.flechas:
            if not flecha.activa:
                continue
            flecha.actualizar()
            if not flecha.activa:
                self._recompensar_tiro_cercano(flecha)
                continue

            # Chequeo colisión con enemigos
            for enemigo in self.enemigos:
                if not enemigo.vivo:
                    continue
                dx = enemigo.x - flecha.x
                dy = enemigo.y - flecha.y
                if dx * dx + dy * dy <= (enemigo.r + 4) ** 2:
                    enemigo.vivo = False
                    flecha.activa = False
                    self.bajas += 1
                    if enemigo.tipo == "corredor":
                        self.shaping += 3.0 # Recompensa extra por eliminar a los corredores rápidos
                    break
        
        self.enemigos = [e for e in self.enemigos if e.vivo]
        self.flechas = [f for f in self.flechas if f.activa] 
class Entrenador:
    def __init__(self):
        self.generacion = 1
        self.cerebros =[Cerebro() for _ in range (POBLACION)]
        self.historial = []
        self.ultimos_sobrevivientes ="-"
        self.nuevas_partidas()
    
    def nuevas_partidas(self):
        #inicia 100 partidas al miso tiempo con la misma semilla para que sea "justo"
        semilla = random.randrange(10 ** 9)
        self.juegos = [Juego(semilla) for _ in self.cerebros]
        self.vivos = POBLACION
        self.frame = 0

    def avanzar(self):
        #Avanza 1 frame para todos los arqueros vivos
        vivos=0
        for cerebro, juego in zip(self.cerebros, self.juegos):
            if juego.terminado:
                continue
            # Solo si no se está recargando (cooldown), ni tensando la cuerda actualmente, y hay enemigos a la vista
            if juego.cool <= 0 and not juego.cargando and juego.enemigos:
                potencia, angulo_01 = cerebro.forward(juego.sensores()) # usa sus sensores para calcular potencia y angulo
                angulo_grados = ANG_MIN + (ANG_MAX - ANG_MIN) * angulo_01 # convierte el valor entre 0 y 1 a grados
                juego.preparar_disparo(potencia, angulo_grados)

            juego.actualizar()
            if not juego.terminado:
                vivos += 1
        if vivos >0:
            self.frame += 1
        self.vivos = vivos
        return vivos #Cuantoss arqueros siguen vivos
    
    def evolucionar(self):
        #Ordena los cerebros de mayor a menor fitness
        puntajes = [j.fitness() for j in self.juegos]
        orden = sorted(range(POBLACION),key=lambda i: puntajes[i], reverse=True)
        mejor_puntaje = puntajes[orden[0]]
        promedio = sum(puntajes) / POBLACION
        self.historial.append((mejor_puntaje,promedio))
        self.ultimos_sobrevivientes = sum (j.vidas > 0 for j in self.juegos)
        elites = [self.cerebros[i] for i in orden[:ELITE]]
        nueva_generacion = [e.clonar() for e in elites]

        pesos_seleccion = [ELITE - r for r in range(ELITE)]
        while len(nueva_generacion) < POBLACION:
            if random.random()<0.3:
                #30% de cruzar genes entre elites
                padre1,padre2 = random.choices(elites,weights=pesos_seleccion, k=2)
                hijo=Cerebro.cruzar(padre1,padre2)
            else:
                padre = random.choices (elites, weights=pesos_seleccion)[0]
                hijo = padre.clonar()
            hijo.mutar(MUTACION, random.choice(MUTACION_SIGMAS))
            nueva_generacion.append(hijo)
        self.cerebros = nueva_generacion
        self.generacion += 1
        self.nuevas_partidas()
class App:
    CELDA = 17  # Tamaño en píxeles de cada celda de la cuadrícula de arqueros

    def __init__(self, root):
        self.root = root
        self.root.title("Arquerito Inteligente TD")
        self.root.configure(bg=BG_UI)
        root.resizable(False, False)

        self.modo = "manual"
        self.juego_manual = Juego()
        self.entrenador = None
        self.indice_vista = 0  # Índice del arquero visualizado en pantalla (0 a 99)

        self.mouse = (ANCHO / 2, ALTO / 2)
        self.tiempo_presionado = None
        self.angulo_apuntado = 20.0

        self._construir_interfaz()
        self.dibujar_escenario()
        self.loop()

    def _construir_interfaz(self):
        main = tk.Frame(self.root, bg=BG_UI)
        main.pack(padx=10, pady=10)

        # --- COLUMNA IZQUIERDA: JUEGO ---
        izquierda = tk.Frame(main, bg=BG_UI)
        izquierda.pack(side="left", anchor="n")

        tk.Label(izquierda, text="ARQUERITO INTELIGENTE", font=("Segoe UI", 16, "bold"),
                 fg=ACENTO, bg=BG_UI).pack(anchor="w")

        self.canvas = tk.Canvas(izquierda, width=ANCHO, height=ALTO, bg="#0f1028", highlightthickness=0)
        self.canvas.pack()

        self.ayuda = tk.Label(izquierda, bg=BG_UI, fg=MUTED, font=("Segoe UI", 9))
        self.ayuda.pack(anchor="w", pady=(4, 0))

        # --- COLUMNA DERECHA: PANEL DE CONTROL ---
        panel = tk.Frame(main, bg=PANEL, padx=14, pady=12)
        panel.pack(side="left", fill="y", padx=(10, 0))

        # 1. Selector de Modo
        self._seccion(panel, "MODO")
        self.modo_var = tk.StringVar(value="manual")
        for texto, val in (("Jugar (manual)", "manual"), ("Entrenar IA", "ia")):
            tk.Radiobutton(panel, text=texto, variable=self.modo_var, value=val, command=self.cambiar_modo,
                           indicatoron=False, bg="#2a2d45", fg=TEXTO, selectcolor="#3f4a8a",
                           font=("Segoe UI", 9, "bold"), pady=4, cursor="hand2").pack(fill="x", pady=2)

        # 2. Controles de Entrenamiento
        self._seccion(panel, "ENTRENAMIENTO")
        self._boton(panel, "Siguiente generación ▶", self.siguiente_generacion)
        self._boton(panel, "Reiniciar entrenamiento", self.reiniciar_entrenamiento)

        self.auto_avanzar = tk.BooleanVar(value=True)
        tk.Checkbutton(panel, text="Auto-avanzar generación", variable=self.auto_avanzar,
                       bg=PANEL, fg=TEXTO, selectcolor="#2a2d45", font=("Segoe UI", 9)).pack(anchor="w", pady=2)

        tk.Label(panel, text="Velocidad de simulación", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        self.velocidad = tk.IntVar(value=3)
        tk.Scale(panel, from_=1, to=50, orient="horizontal", variable=self.velocidad, bg=PANEL, fg=TEXTO,
                 troughcolor="#2a2d45", highlightthickness=0, length=180).pack(anchor="w")

        # 3. Cuadrícula de Población (10x10)
        self._seccion(panel, "POBLACIÓN (clic para ver)")
        tam = self.CELDA * 10
        self.cuadricula = tk.Canvas(panel, width=tam, height=tam, bg="#14162a", highlightthickness=0, cursor="hand2")
        self.cuadricula.pack(anchor="w", pady=4)
        self.celdas = []
        for i in range(POBLACION):
            r, c = divmod(i, 10)
            x, y = c * self.CELDA + 1, r * self.CELDA + 1
            rect = self.cuadricula.create_rectangle(x, y, x + self.CELDA - 3, y + self.CELDA - 3, fill="#2a2d45", outline="")
            self.celdas.append(rect)
        self.cuadricula.bind("<Button-1>", self.al_click_cuadricula)

        leyenda = tk.Frame(panel, bg=PANEL)
        leyenda.pack(anchor="w", pady=(2, 0))
        for txt, col in (("■ vivo", "#3ddc97"), ("■ muerto", "#7a2638"), ("■ sobrevivió", "#4361ee"), ("□ élite", "#ffd166")):
            tk.Label(leyenda, text=txt, fg=col, bg=PANEL, font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))

        # 4. Estadísticas
        self._seccion(panel, "ESTADÍSTICAS")
        self.lbl_stats = tk.Label(panel, bg=PANEL, fg=TEXTO, font=("Consolas", 9), justify="left", anchor="w")
        self.lbl_stats.pack(anchor="w", fill="x")

        # Eventos de entrada
        self.canvas.bind("<Motion>", self.al_mover_mouse)
        self.canvas.bind("<B1-Motion>", self.al_mover_mouse)
        self.canvas.bind("<ButtonPress-1>", self.al_presionar_mouse)
        self.root.bind("<ButtonRelease-1>", self.al_soltar_mouse)
        self.root.bind("<KeyPress-r>", lambda e: self.reiniciar())
        self.root.bind("<KeyPress-R>", lambda e: self.reiniciar())
        self.root.bind("<space>", lambda e: self.siguiente_generacion())
        self._actualizar_ayuda()

    def _seccion(self, parent, texto):
        tk.Label(parent, text=texto, bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(8, 2))

    def _boton(self, parent, texto, comando):
        b = tk.Button(parent, text=texto, command=comando, bg="#2a2d45", fg=TEXTO,
                      activebackground=ACENTO2, activeforeground="#111", relief="flat",
                      font=("Segoe UI", 9, "bold"), pady=4, cursor="hand2")
        b.pack(fill="x", pady=2)
        return b

    def cambiar_modo(self):
        self.modo = self.modo_var.get()
        self.tiempo_presionado = None
        if self.modo == "ia" and self.entrenador is None:
            self.entrenador = Entrenador()
        self._actualizar_ayuda()

    def siguiente_generacion(self):
        if self.entrenador is None or self.modo != "ia":
            return
        # Si todavía hay arqueros vivos jugando la oleada, simulamos rápidamente hasta el final
        # para que todos los arqueros sean evaluados con sus bajas y puntuaciones reales
        while self.entrenador.vivos > 0:
            if not self.entrenador.avanzar():
                break
        self.entrenador.evolucionar()
        self.indice_vista = 0

    def reiniciar_entrenamiento(self):
        self.entrenador = Entrenador()
        self.indice_vista = 0

    def al_click_cuadricula(self, ev):
        if self.entrenador is None:
            return
        col = int(ev.x // self.CELDA)
        fila = int(ev.y // self.CELDA)
        idx = fila * 10 + col
        if 0 <= idx < POBLACION:
            self.indice_vista = idx

    def _actualizar_cuadricula(self):
        if self.entrenador is None:
            return
        for i, juego in enumerate(self.entrenador.juegos):
            if not juego.terminado:
                color = "#3ddc97"
            else:
                color = "#7a2638" if juego.vidas <= 0 else "#4361ee"

            if i == self.indice_vista:
                borde, grosor = "#ffffff", 2
            elif self.entrenador.generacion > 1 and i < ELITE:
                borde, grosor = "#ffd166", 1
            else:
                borde, grosor = "", 1

            self.cuadricula.itemconfig(self.celdas[i], fill=color, outline=borde, width=grosor)

    def _actualizar_stats(self):
        if self.modo == "manual":
            g = self.juego_manual
            txt = (f"MODO MANUAL\n\n"
                   f"Vidas:      {g.vidas}/{VIDAS}\n"
                   f"Bajas:      {g.bajas}\n"
                   f"Tiempo:     {g.tiempo / 60:.1f} s")
        else:
            if self.entrenador is None:
                return
            t = self.entrenador
            g = t.juegos[self.indice_vista]
            puntajes = [j.fitness() for j in t.juegos]
            mejor_ahora = max(puntajes) if puntajes else 0.0
            record = f"{max(h[0] for h in t.historial):.1f}" if t.historial else "-"
            txt = (f"Generación:  {t.generacion}\n"
                   f"Vivos:       {t.vivos}/{POBLACION}\n"
                   f"Tiempo:      {t.frame / 60:.1f}/{MAX_DURACION_GENERACION // 60} s\n"
                   f"Mejor ahora: {mejor_ahora:.1f}\n"
                   f"Récord:      {record}\n"
                   f"Sobrev. ant: {t.ultimos_sobrevivientes}\n\n"
                   f"Viendo #{self.indice_vista + 1}:\n"
                   f"  Bajas:     {g.bajas}\n"
                   f"  Vidas:     {g.vidas}\n"
                   f"  Puntaje:   {g.fitness():.1f}")
            if t.vivos == 0 and not self.auto_avanzar.get():
                txt += "\n\n⏸ Gen terminada.\nPulsa Siguiente ▶"
        self.lbl_stats.config(text=txt)

    def _actualizar_ayuda(self):
        if self.modo == "manual":
            self.ayuda.config(text="Modo manual: Mantén presionado para cargar potencia · El mouse define el ángulo · R reinicia")
        else:
            self.ayuda.config(text="Modo IA: 100 agentes compiten simultáneamente · Haz clic en la cuadrícula para observar a cualquiera · Espacio avanza")

    def al_mover_mouse(self, ev):
        self.mouse = (ev.x, ev.y)

    def al_presionar_mouse(self, ev):
        if self.modo == "manual" and self.juego_manual.vidas > 0:
            self.tiempo_presionado = time.time()

    def al_soltar_mouse(self, ev):
        if self.modo == "manual" and self.tiempo_presionado is not None:
            self.juego_manual.disparar(self.calcular_potencia(), self.calcular_angulo())
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
        if self.modo == "manual":
            self.juego_manual = Juego()
            self.tiempo_presionado = None

    def loop(self):
        if self.modo == "manual":
            self.juego_manual.actualizar()
            self.dibujar_entidades(self.juego_manual, es_manual=True)
        else:
            if self.entrenador is None:
                self.entrenador = Entrenador()

            # Modo IA: simulamos N pasos según el slider de velocidad
            pasos = self.velocidad.get()
            for _ in range(pasos):
                vivos = self.entrenador.avanzar()
                if vivos == 0:
                    if self.auto_avanzar.get():
                        self.entrenador.evolucionar()
                    break

            # Dibujamos al arquero seleccionado actualmente
            juego_actual = self.entrenador.juegos[self.indice_vista]
            cerebro_actual = self.entrenador.cerebros[self.indice_vista]
            self.dibujar_entidades(juego_actual, es_manual=False, cerebro=cerebro_actual)
            self._actualizar_cuadricula()

        self._actualizar_stats()
        self.root.after(16, self.loop)

    def dibujar_entidades(self, juego, es_manual=True, cerebro=None):
        c = self.canvas
        T = "dyn"     # Etiqueta que indica que un elemento se mueve y hay que redibujarlo
        c.delete(T)   # Borra los elementos móviles de los frames anteriores

        if es_manual:
            self.angulo_apuntado = self.calcular_angulo()
            ang = self.angulo_apuntado
            p = self.calcular_potencia()
        else:
            if juego.cargando:
                ang = juego.carga_angulo
                p = juego.potencia_actual()
            else:
                angulo_01 = cerebro.salida[1] if cerebro else 0.5
                ang = ANG_MIN + (ANG_MAX - ANG_MIN) * angulo_01
                p = 0.0
            self.angulo_apuntado = ang

        rad = math.radians(ang)

        # Línea punteada de apuntado
        L = 30 + 90 * p
        if es_manual:
            c.create_line(ARQUERO_X, ARQUERO_Y, ARQUERO_X + L * math.cos(rad), ARQUERO_Y - L * math.sin(rad),
                          dash=(4, 4), fill="#ffffff" if self.tiempo_presionado else "#777777", tags=T)

            # Barra de carga de potencia
            bx, by = 10, PISO - 228
            c.create_rectangle(bx, by, bx + 72, by + 10, outline="#e8e6f0", tags=T)
            if p > 0:
                c.create_rectangle(bx + 1, by + 1, bx + 1 + 70 * p, by + 9, fill="#f4a261", outline="", tags=T)
            if juego.cool > 0:
                c.create_rectangle(bx, by + 13, bx + 72 * juego.cool / COOLDOWN, by + 16, fill=MUTED, outline="", tags=T)
        else:
            c.create_line(ARQUERO_X, ARQUERO_Y, ARQUERO_X + L * math.cos(rad), ARQUERO_Y - L * math.sin(rad),
                          dash=(4, 4), fill=ACENTO2, tags=T)

            # Barra de carga de potencia para la IA (muestra visual de la tensión del arco)
            bx, by = 10, PISO - 228
            c.create_rectangle(bx, by, bx + 72, by + 10, outline="#e8e6f0", tags=T)
            if p > 0:
                c.create_rectangle(bx + 1, by + 1, bx + 1 + 70 * p, by + 9, fill=ACENTO2, outline="", tags=T)
            if juego.cool > 0:
                c.create_rectangle(bx, by + 13, bx + 72 * juego.cool / COOLDOWN, by + 16, fill=MUTED, outline="", tags=T)

            t = self.entrenador
            tag = "  (élite)" if t and t.generacion > 1 and self.indice_vista < ELITE else ""
            c.create_text(ANCHO / 2, 16, text=f"Gen {t.generacion} · Arquero #{self.indice_vista + 1}{tag}",
                          fill=ACENTO2, font=("Segoe UI", 12, "bold"), tags=T)

        # Cartel de GAME OVER si la partida termina
        if juego.vidas <= 0 or juego.terminado:
            c.create_rectangle(0, 0, ANCHO, ALTO, fill="#000000", stipple="gray50", outline="", tags=T)
            msg = "GAME OVER" if juego.vidas <= 0 else "¡SOBREVIVIÓ!"
            sub = "Pulsa R para reiniciar" if es_manual else (
                "Esperando siguiente generación" if self.entrenador and self.entrenador.vivos == 0 else "Arquero terminado")
            c.create_text(ANCHO / 2, ALTO / 2 - 18, text=msg, fill="#f4a261", font=("Segoe UI", 34, "bold"), tags=T)
            c.create_text(ANCHO / 2, ALTO / 2 + 22, text=sub, fill="#e8e6f0", font=("Segoe UI", 12), tags=T)

        # Arquero
        ax = ARQUERO_X - 9
        c.create_line(ax, PISO - 145, ax, PISO - 162, fill="#2b2d42", width=5, tags=T)  # Cuerpo
        c.create_oval(ax - 5, PISO - 173, ax + 5, PISO - 163, fill="#f1c27d", outline="", tags=T)  # Cabeza
        c.create_arc(ax - 6, PISO - 176, ax + 6, PISO - 164, start=0, extent=180, fill="#2d6a4f", outline="", tags=T)  # Gorro

        # Extremos del arco
        R = 15
        p1 = (ARQUERO_X + R * math.cos(math.radians(ang - 75)), ARQUERO_Y - R * math.sin(math.radians(ang - 75)))
        p2 = (ARQUERO_X + R * math.cos(math.radians(ang + 75)), ARQUERO_Y - R * math.sin(math.radians(ang + 75)))

        # Retroceso de la cuerda hacia atrás proporcional a la potencia cargada (tensión)
        retroceso = 14 * p
        pm = ((p1[0] + p2[0]) / 2 - retroceso * math.cos(rad),
              (p1[1] + p2[1]) / 2 + retroceso * math.sin(rad))

        # Cuerda tensada en dos tramos
        c.create_line(p1[0], p1[1], pm[0], pm[1], fill="#eeeeee", width=1, tags=T)
        c.create_line(pm[0], pm[1], p2[0], p2[1], fill="#eeeeee", width=1, tags=T)

        # Brazo frontal que sostiene el arco
        c.create_line(ax, PISO - 157, ARQUERO_X, ARQUERO_Y, fill="#2b2d42", width=3, tags=T)
        # Brazo trasero que estira la cuerda
        c.create_line(ax, PISO - 157, pm[0], pm[1], fill="#2b2d42", width=3, tags=T)

        # Madera del arco
        c.create_arc(ARQUERO_X - R, ARQUERO_Y - R, ARQUERO_X + R, ARQUERO_Y + R, start=ang - 75, extent=150, style="arc", outline="#d4a373", width=3, tags=T)

        # Flecha apoyada en la cuerda si hay tensión
        if p > 0.05:
            punta_x = pm[0] + 20 * math.cos(rad)
            punta_y = pm[1] - 20 * math.sin(rad)
            c.create_line(pm[0], pm[1], punta_x, punta_y, fill="#f4e9cd", width=2, arrow=tk.LAST, arrowshape=(7, 8, 3), tags=T)

        # Enemigos
        for e in juego.enemigos:
            self.dibujar_enemigo(e, juego.tiempo, T)

        # Flechas
        for f in juego.flechas:
            th = math.atan2(f.vy, f.vx)
            c.create_line(f.x - math.cos(th) * 20, f.y - math.sin(th) * 20, f.x, f.y, fill="#f4e9cd", width=2, arrow=tk.LAST, arrowshape=(7, 8, 3), tags=T)

        # HUD
        c.create_text(20, 20, anchor="nw", text=f"VIDAS: {juego.vidas} | BAJAS: {juego.bajas}", fill="#e8e6f0", font=("Segoe UI", 12, "bold"), tags=T) 
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


