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
NEG = "#f72585"
NN_BG = "#0d0f1a"

NOMBRES_ENTRADAS = [
    "Dist E1", "Alt E1", "VelX E1", "VelY E1",
    "Dist E2", "Alt E2", "VelX E2", "VelY E2",
    "Cantidad"
]
NOMBRES_SALIDAS = ["Potencia", "Ángulo"]


def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def blend(c1, c2, t):
    """Interpola dos colores hexadecimales con factor t entre 0.0 y 1.0."""
    t = max(0.0, min(1.0, t))
    a, b = _hex(c1), _hex(c2)
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

ANCHO, ALTO = 960, 440
PISO = 390
CASTILLO_X = 80
ARQUERO_X, ARQUERO_Y = 58, PISO - 155
GRAVEDAD = 0.25
VIDAS = 5
V_MIN, V_MAX = 5.0, 17.5
ANG_MIN, ANG_MAX = -80.0, 30.0 # Rango tenso único: de la puerta (-80°) a tiro largo (+30°), sin tiros globo
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
SENSORES_ENTRADA = 9 # 9 sensores: dist, alt, vel_x, vel_y para los 2 más cercanos + cantidad total
SENSORES_OCULTA = 12 #Aumentado de 8 a 12 para facilitar el cálculo balístico de objetivos rápidos (corredores)
NEURONAS_SALIDA = 2 #La idea es que la ia decida con que angulo disparar y con qué potencia

POBLACION = 100 #Comenzamos con 100 arqueros que nos interesa que mejoren con cada generación
ELITE = 10 #Los 10 mejores son los que pasan con sus pesos intactos a la siguiente generación, el resto se les cambia
MUTACION = 0.08 # 8% probabilidad de mutación por peso (afina puntería sin destruir lo aprendido)
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
        self.vy = 0.0 # Velocidad vertical por frame

    def actualizar(self, frame_juego):#frame_juego es para que todos los enemigos se muevan al mismo ritmo
        self.x -= self.vel #se acerca a nuestro cero, o sea, nuestro castillo
        y_ant = self.y
        if self.vuela:                
            self.y = self.base_y + math.sin(frame_juego *0.07 + self.phase) * 22 #Esto indica un movimiento senoidal en el eje y
        self.vy = self.y - y_ant # Velocidad vertical real del frame (permite a la red predecir subida/bajada)
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

    def subpaso(self):
        # Avanza 0.5 frames para evitar que la flecha atraviese enemigos a alta velocidad (túnel)
        self.vy += GRAVEDAD * 0.5
        self.x += self.vx * 0.5
        self.y += self.vy * 0.5
        if self.objetivo is not None:
            d = math.hypot(self.objetivo.x - self.x, self.objetivo.y - self.y)
            if d < self.mejor_distancia:
                self.mejor_distancia = d

    def actualizar(self):
        self.subpaso()
        self.subpaso()
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
        self.shaping = 0.0 # Puntos auxiliares por tiros cercanos (máx 1.5 pts por flecha)
        self.terminado = False # Si termina el run de la ia
        self.bolsa_spawn = [] # Bolsa de tipos para spawn balanceado sin sesgo de semilla

        # Simulación de tensión y carga del arco (tiempo que el arquero mantiene la cuerda estirada)
        self.cargando = False
        self.carga_potencia = 0.0
        self.carga_angulo = 0.0
        self.carga_objetivo = None # Objetivo fijado al iniciar el tensado (evita desfase de 12 frames)
        self.frames_carga = 0
        self.frames_carga_total = 0

    def preparar_disparo(self, potencia_normalizada, angulo_grados):
        # La IA tensa el arco; el tiempo de tensado es constante (FRAMES_TENSADO)
        if self.vidas <= 0 or self.cool > 0 or self.cargando:
            return False
        self.cargando = True
        self.carga_potencia = max(0.1, min(1.0, potencia_normalizada))
        self.carga_angulo = angulo_grados
        # Fijamos el objetivo en el momento que la red decide disparar
        self.carga_objetivo = min(self.enemigos, key=lambda e: e.x) if self.enemigos else None
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
        # Shaping bajo (máx 1.5 pts): elimina el exploit de "farming"; matar (10 pts) siempre es superior
        RADIO_SHAPING = 160.0
        if flecha.mejor_distancia < RADIO_SHAPING:
            self.shaping += max(0.0, 1.0 - flecha.mejor_distancia / RADIO_SHAPING) * 1.5
    
    def sensores(self): 
        # 9 sensores: dist, alt, vel_x, vel_y para los 2 más cercanos + cantidad total
        cercanos = sorted(self.enemigos, key=lambda e: e.x)[:2]
        datos = []
        for i in range(2):
            if i < len(cercanos):
                e = cercanos[i]
                distancia = (e.x - CASTILLO_X) / (ANCHO - CASTILLO_X)
                altura = (PISO - e.y) / 200.0
                vel_x = e.vel / 4.0
                vel_y = (e.vy + 2.0) / 4.0 # Normalizado entre 0 y 1 (-2 a +2 px/frame)
                datos.extend([distancia, altura, vel_x, vel_y])
            else:
                datos.extend([1.0, 0.0, 0.0, 0.5])
        cantidad_normalizada = min(len(self.enemigos), 10) / 10.0
        datos.append(cantidad_normalizada)
        return datos

    def spawn(self):
        self.spawn_timer -= 1
        if self.spawn_timer > 0:
            return
        diff = min(1.0, self.tiempo / (60 * 60)) # La dificultad sube durante 60 seg
        # Bolsa equilibrada: garantiza misma variedad en cada ciclo de 10 enemigos (evita overfitting de semilla)
        if not self.bolsa_spawn:
            bolsa = ["soldado"] * 4 + ["corredor"] * 2 + ["tanque"] * 2 + ["murcielago"] * 2
            self.rng.shuffle(bolsa)
            self.bolsa_spawn = bolsa
        tipo = self.bolsa_spawn.pop()
        e = Enemigo(tipo, self.rng)
        e.vel *= 1 + 0.5 * diff # La velocidad aumenta con la dificultad
        self.enemigos.append(e)
        self.spawn_timer = int(self.rng.uniform(90, 150) * (1 - 0.5 * diff))

    def disparar(self, potencia_normalizada, angulo_grados, cool=COOLDOWN, objetivo=None):
        if self.vidas <= 0 or self.cool > 0:
            return False
        potencia = V_MIN + (V_MAX - V_MIN) * max(0.0, min(1.0, potencia_normalizada))
        if objetivo is None:
            objetivo = min(self.enemigos, key=lambda e: e.x) if self.enemigos else None
        nueva_flecha = Flecha(ARQUERO_X, ARQUERO_Y, potencia, angulo_grados, objetivo)
        self.flechas.append(nueva_flecha)
        self.cool = cool
        return True
    
    def fitness(self):
        vidas_perdidas = VIDAS - self.vidas
        # Penalización severa por vida (-20 pts): dejar pasar enemigos para farmear destruye el score
        return self.bajas * 10.0 + self.shaping - vidas_perdidas * 20.0 + (self.tiempo / 60.0) * 1.0

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
                self.disparar(self.carga_potencia, self.carga_angulo, cool=max(1, COOLDOWN - FRAMES_TENSADO), objetivo=self.carga_objetivo)

        self.spawn()

        for enemigo in self.enemigos:
            enemigo.actualizar(self.tiempo)
            if enemigo.x - enemigo.r <= CASTILLO_X:
                self.vidas -= 1
                enemigo.vivo = False # El enemigo al tocar el castillo se borra y quita una vida

        for flecha in self.flechas:
            if not flecha.activa:
                continue
            impacto = False
            for _ in range(2): # 2 sub-pasos por frame para evitar efecto túnel a alta velocidad
                flecha.subpaso()
                if flecha.y >= PISO:
                    flecha.y = PISO
                    flecha.activa = False
                    self._recompensar_tiro_cercano(flecha)
                    break
                elif flecha.x > ANCHO + 50 or flecha.x < -50:
                    flecha.activa = False
                    self._recompensar_tiro_cercano(flecha)
                    break

                # Chequeo colisión con enemigos en cada sub-paso
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
                            self.shaping += 3.0 # Recompensa extra por abatir corredores rápidos
                        impacto = True
                        break
                if impacto:
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


# ======================= VENTANA DE LA RED NEURONAL ========================
class VentanaRed:
    ANCHO_V, ALTO_V = 660, 600

    def __init__(self, root):
        self.top = tk.Toplevel(root)
        self.top.title("Red neuronal · Pesos y decisiones en vivo")
        self.top.configure(bg=BG_UI)
        self.top.resizable(False, False)
        self.c = tk.Canvas(self.top, width=self.ANCHO_V, height=self.ALTO_V, bg=NN_BG, highlightthickness=0)
        self.c.pack(padx=8, pady=8)
        self.abierta = True
        self.hover = None
        self.top.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.c.bind("<Motion>", self.al_mover_mouse)
        self.c.bind("<Leave>", lambda e: setattr(self, "hover", None))

        # Coordenadas (x, y) de cada neurona
        self.pos = {}
        # 10 nodos de entrada (9 sensores + 1 bias)
        self._columna("i", SENSORES_ENTRADA + 1, 175, 55, 385)
        # 13 nodos ocultos (12 neuronas + 1 bias)
        self._columna("h", SENSORES_OCULTA + 1, 360, 48, 392)
        # 2 nodos de salida (Potencia, Ángulo)
        self._columna("o", NEURONAS_SALIDA, 525, 170, 270)

    def _columna(self, capa, n, x, y0, y1):
        paso = (y1 - y0) / (n - 1) if n > 1 else 0
        for k in range(n):
            self.pos[(capa, k)] = (x, y0 + k * paso)

    def cerrar(self):
        self.abierta = False
        self.top.destroy()

    def al_mover_mouse(self, ev):
        self.hover = None
        for clave, (x, y) in self.pos.items():
            if (ev.x - x) ** 2 + (ev.y - y) ** 2 < 15 ** 2:
                self.hover = clave
                break

    @staticmethod
    def _color_peso(w):
        return blend(NN_BG, ACENTO2 if w > 0 else NEG, 0.2 + min(0.8, abs(w) / 2.5))

    @staticmethod
    def _color_nodo(a):
        return blend("#1b1f33", ACENTO2 if a > 0 else NEG, min(1.0, abs(a)))

    def actualizar(self, cerebro, titulo, historial):
        c = self.c
        c.delete("all")
        P = self.pos
        c.create_text(16, 12, anchor="nw", text=titulo, fill=TEXTO, font=("Segoe UI", 12, "bold"))
        for txt, x in (("Entradas", 175), ("Oculta (tanh)", 360), ("Salidas (sigmoide)", 525)):
            c.create_text(x, 34, text=txt, fill=MUTED, font=("Segoe UI", 9))

        inp = cerebro.entrada + [1.0]
        hid = cerebro.oculta + [1.0]
        hv = self.hover

        # --- Conexiones sinápticas (peso > 0 azul, peso < 0 rosa) ---
        def dibujar_linea(a, b, w, resalta):
            (x1, y1), (x2, y2) = P[a], P[b]
            grosor = 1 + min(3.5, abs(w) * 1.2)
            color = (ACENTO2 if w > 0 else NEG) if resalta else self._color_peso(w)
            c.create_line(x1, y1, x2, y2, fill=color, width=grosor + (1.5 if resalta else 0))

        for j in range(SENSORES_OCULTA):
            for i in range(SENSORES_ENTRADA + 1):
                dibujar_linea(("i", i), ("h", j), cerebro.w_ih(i, j), hv in (("i", i), ("h", j)))

        for k in range(NEURONAS_SALIDA):
            for j in range(SENSORES_OCULTA + 1):
                dibujar_linea(("h", j), ("o", k), cerebro.w_ho(j, k), hv in (("h", j), ("o", k)))

        # --- Neuronas ---
        def dibujar_nodo(clave, val, etiqueta, es_bias=False):
            x, y = P[clave]
            r = 10 if clave[0] == "h" else 11
            relleno = "#3a3d55" if es_bias else self._color_nodo(val)
            borde = "#ffffff" if clave == hv else "#555a7a"
            c.create_oval(x - r, y - r, x + r, y + r, fill=relleno, outline=borde, width=2 if clave == hv else 1)
            c.create_text(x, y, text=etiqueta, fill=TEXTO, font=("Segoe UI", 7, "bold"))

        for i in range(SENSORES_ENTRADA + 1):
            es_bias = (i == SENSORES_ENTRADA)
            dibujar_nodo(("i", i), inp[i], "b" if es_bias else str(i + 1), es_bias)
            x, y = P[("i", i)]
            nombre = "Bias" if es_bias else NOMBRES_ENTRADAS[i]
            c.create_text(x - 18, y, anchor="e", text=f"{nombre}  {inp[i]:+.2f}",
                          fill=MUTED if es_bias else TEXTO, font=("Consolas", 8))

        for j in range(SENSORES_OCULTA + 1):
            es_bias = (j == SENSORES_OCULTA)
            dibujar_nodo(("h", j), hid[j], "b" if es_bias else f"H{j + 1}", es_bias)

        potencia, ang01 = cerebro.salida
        angulo = ANG_MIN + (ANG_MAX - ANG_MIN) * ang01
        vel = V_MIN + (V_MAX - V_MIN) * potencia
        for k, txt in enumerate((f"Potencia\n{potencia:.0%}", f"Ángulo\n{angulo:.1f}°")):
            dibujar_nodo(("o", k), cerebro.salida[k], "P" if k == 0 else "A")
            x, y = P[("o", k)]
            c.create_text(x + 20, y, anchor="w", text=txt, fill=ACENTO, font=("Segoe UI", 10, "bold"))

        # --- Panel de decisión del disparo ---
        c.create_rectangle(16, 405, self.ANCHO_V - 16, 435, fill="#171a2b", outline="#2c3050")
        c.create_text(self.ANCHO_V / 2, 420, fill=TEXTO, font=("Segoe UI", 10),
                      text=f"Decisión → disparar a {angulo:.1f}° con {potencia:.0%} de potencia ({vel:.1f} px/frame)")

        self._grafico_fitness(historial)
        self._panel_detalle(cerebro, inp)

    def _grafico_fitness(self, historial):
        c = self.c
        x0, y0, x1, y1 = 20, 448, 330, 585
        c.create_rectangle(x0, y0, x1, y1, outline="#2c3050", fill="#121526")
        c.create_text(x0 + 6, y0 - 9, anchor="w", text="Puntaje por generación",
                      fill=MUTED, font=("Segoe UI", 9))
        if not historial:
            c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="Aún no hay generaciones completas",
                          fill=MUTED, font=("Segoe UI", 9))
            return
        valores = [v for h in historial for v in h]
        lo = min(0.0, min(valores))
        hi = max(1.0, max(valores)) * 1.1
        n = len(historial)

        def punto(i, v):
            x = x0 + 10 + (x1 - x0 - 20) * (i / max(1, n - 1))
            y = y1 - 8 - (y1 - y0 - 16) * (v - lo) / max(0.001, hi - lo)
            return x, y

        for idx, color in ((1, ACENTO2), (0, "#ffd166")):
            pts = [punto(i, h[idx]) for i, h in enumerate(historial)]
            if len(pts) > 1:
                c.create_line(*[p for xy in pts for p in xy], fill=color, width=2, smooth=True)
            for x, y in pts[-1:]:
                c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline="")
        c.create_text(x1 - 6, y0 + 8, anchor="ne", fill="#ffd166", font=("Segoe UI", 8),
                      text=f"mejor {historial[-1][0]:.1f}")
        c.create_text(x1 - 6, y0 + 22, anchor="ne", fill=ACENTO2, font=("Segoe UI", 8),
                      text=f"promedio {historial[-1][1]:.1f}")

    def _panel_detalle(self, cerebro, inp):
        c = self.c
        x0, y0, x1, y1 = 345, 448, self.ANCHO_V - 16, 585
        c.create_rectangle(x0, y0, x1, y1, outline="#2c3050", fill="#121526")
        c.create_text(x0 + 6, y0 - 9, anchor="w", text="Detalle de neurona", fill=MUTED, font=("Segoe UI", 9))
        hv = self.hover
        if hv is None:
            lineas = [
                "Pasa el mouse sobre una neurona",
                "para ver sus pesos numéricos.",
                "",
                "Azul = peso positivo (excitatorio)",
                "Rosa = peso negativo (inhibitorio)",
                "Grosor = magnitud del peso"
            ]
        else:
            capa, k = hv
            if capa == "i":
                nombre = "Bias" if k == SENSORES_ENTRADA else NOMBRES_ENTRADAS[k]
                lineas = [f"Entrada: {nombre} ({inp[k]:+.2f})", "Pesos hacia capa oculta:"]
                for j in range(0, SENSORES_OCULTA, 2):
                    p1 = f"H{j+1}:{cerebro.w_ih(k, j):+.2f}"
                    p2 = f"H{j+2}:{cerebro.w_ih(k, j+1):+.2f}" if j + 1 < SENSORES_OCULTA else ""
                    lineas.append(f"  {p1:<12} {p2}")
            elif capa == "h" and k == SENSORES_OCULTA:
                lineas = ["Bias de capa oculta", "Pesos hacia salidas:"]
                lineas += [f"  -> {NOMBRES_SALIDAS[o]}: {cerebro.w_ho(k, o):+.3f}" for o in range(NEURONAS_SALIDA)]
            elif capa == "h":
                lineas = [f"H{k + 1}  activación: {cerebro.oculta[k]:+.3f}", "Pesos desde entradas:"]
                for i in range(0, SENSORES_ENTRADA + 1, 2):
                    nom1 = "Bias" if i == SENSORES_ENTRADA else NOMBRES_ENTRADAS[i]
                    p1 = f"{nom1}:{cerebro.w_ih(i, k):+.2f}"
                    if i + 1 <= SENSORES_ENTRADA:
                        nom2 = "Bias" if i + 1 == SENSORES_ENTRADA else NOMBRES_ENTRADAS[i + 1]
                        p2 = f"{nom2}:{cerebro.w_ih(i + 1, k):+.2f}"
                    else:
                        p2 = ""
                    lineas.append(f"  {p1:<14} {p2}")
            else:
                lineas = [f"{NOMBRES_SALIDAS[k]}  salida: {cerebro.salida[k]:.3f}", "Pesos desde oculta:"]
                for j in range(0, SENSORES_OCULTA + 1, 2):
                    nom1 = "Bias" if j == SENSORES_OCULTA else f"H{j + 1}"
                    p1 = f"{nom1}:{cerebro.w_ho(j, k):+.2f}"
                    if j + 1 <= SENSORES_OCULTA:
                        nom2 = "Bias" if j + 1 == SENSORES_OCULTA else f"H{j + 2}"
                        p2 = f"{nom2}:{cerebro.w_ho(j + 1, k):+.2f}"
                    else:
                        p2 = ""
                    lineas.append(f"  {p1:<12} {p2}")
        c.create_text(x0 + 8, y0 + 6, anchor="nw", text="\n".join(lineas[:10]),
                      fill=TEXTO, font=("Consolas", 8))


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
        self.cerebro_demo = Cerebro() # Red de muestra para visualizar en modo manual
        self.indice_vista = 0  # Índice del arquero visualizado en pantalla (0 a 99)
        self.ventana_red = None # Referencia a la ventana de inspección de la red neuronal
        self.tick = 0

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
        self._boton(panel, "Ver red neuronal", self.abrir_red)

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

    def abrir_red(self):
        # Abre o trae al frente la ventana de inspección de la red neuronal
        if self.ventana_red is None or not self.ventana_red.abierta:
            self.ventana_red = VentanaRed(self.root)
        else:
            self.ventana_red.top.lift()

    def _actualizar_red(self):
        if not (self.ventana_red and self.ventana_red.abierta):
            return
        if self.modo == "ia":
            if self.entrenador is None:
                return
            t = self.entrenador
            c, j = t.cerebros[self.indice_vista], t.juegos[self.indice_vista]
            if not j.terminado:
                c.forward(j.sensores())
            titulo = f"Arquero #{self.indice_vista + 1} · Generación {t.generacion}"
            historial = t.historial
        else:
            c = self.entrenador.cerebros[0] if self.entrenador else self.cerebro_demo
            c.forward(self.juego_manual.sensores())
            titulo = "Mejor arquero opinando sobre tu partida" if self.entrenador else "Red neuronal (modo manual)"
            historial = self.entrenador.historial if self.entrenador else []
        self.ventana_red.actualizar(c, titulo, historial)

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

        self.tick += 1
        if self.tick % 3 == 0:
            self._actualizar_stats()
            self._actualizar_red()
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


