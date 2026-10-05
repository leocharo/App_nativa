#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgendaNativa - Aplicación nativa de escritorio (Windows / macOS / Linux)

Gestor de tareas con recordatorios. Está pensada para demostrar las
características de una APLICACIÓN NATIVA:

  - Interfaz con widgets y tema del sistema operativo (ttk + menú nativo).
  - Base de datos local SQLite en la carpeta de datos del usuario (offline).
  - Acceso al sistema de archivos con diálogos nativos (importar/exportar CSV).
  - Notificaciones del sistema operativo (Windows, macOS y Linux).
  - Portapapeles del sistema y atajos de teclado.
  - Lectura de información del equipo (SO, resolución, rutas).

Requisitos: Python 3.9 o superior con Tkinter. No requiere librerías externas.
Ejecución:  python agenda_nativa.py
"""

import csv
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

APP_NAME = "AgendaNativa"
APP_VERSION = "1.0.0"
DATE_FMT = "%Y-%m-%d %H:%M"
CATEGORIAS = ["Escuela", "Trabajo", "Personal", "Salud", "Otros"]
PRIORIDADES = ["Alta", "Media", "Baja"]
CHECK_INTERVAL_MS = 30_000  # revisa recordatorios cada 30 segundos


# --------------------------------------------------------------------------
# Rutas propias de cada sistema operativo
# --------------------------------------------------------------------------
def carpeta_datos() -> str:
    """Devuelve la carpeta de datos de usuario según el sistema operativo."""
    sistema = platform.system()
    if sistema == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sistema == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    ruta = os.path.join(base, APP_NAME)
    os.makedirs(ruta, exist_ok=True)
    return ruta


# --------------------------------------------------------------------------
# Capa de datos (SQLite local, funciona sin internet)
# --------------------------------------------------------------------------
class Base:
    def __init__(self, ruta_db: str):
        self.ruta = ruta_db
        self.con = sqlite3.connect(ruta_db)
        self.con.row_factory = sqlite3.Row
        self.con.execute(
            """CREATE TABLE IF NOT EXISTS tareas (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   titulo TEXT NOT NULL,
                   descripcion TEXT DEFAULT '',
                   categoria TEXT DEFAULT 'Otros',
                   prioridad TEXT DEFAULT 'Media',
                   vencimiento TEXT DEFAULT '',
                   completada INTEGER DEFAULT 0,
                   avisada INTEGER DEFAULT 0,
                   creada TEXT NOT NULL
               )"""
        )
        self.con.commit()

    def listar(self, texto="", estado="Todas"):
        sql = "SELECT * FROM tareas WHERE 1=1"
        params = []
        if texto:
            sql += " AND (titulo LIKE ? OR descripcion LIKE ? OR categoria LIKE ?)"
            params += [f"%{texto}%"] * 3
        if estado == "Pendientes":
            sql += " AND completada = 0"
        elif estado == "Completadas":
            sql += " AND completada = 1"
        sql += (
            " ORDER BY completada ASC,"
            " CASE prioridad WHEN 'Alta' THEN 0 WHEN 'Media' THEN 1 ELSE 2 END,"
            " CASE WHEN vencimiento = '' THEN 1 ELSE 0 END, vencimiento ASC"
        )
        return self.con.execute(sql, params).fetchall()

    def obtener(self, id_):
        return self.con.execute("SELECT * FROM tareas WHERE id = ?", (id_,)).fetchone()

    def insertar(self, titulo, descripcion, categoria, prioridad, vencimiento):
        cur = self.con.execute(
            "INSERT INTO tareas (titulo, descripcion, categoria, prioridad,"
            " vencimiento, creada) VALUES (?,?,?,?,?,?)",
            (titulo, descripcion, categoria, prioridad, vencimiento,
             datetime.now().strftime(DATE_FMT)),
        )
        self.con.commit()
        return cur.lastrowid

    def actualizar(self, id_, titulo, descripcion, categoria, prioridad, vencimiento):
        self.con.execute(
            "UPDATE tareas SET titulo=?, descripcion=?, categoria=?, prioridad=?,"
            " vencimiento=?, avisada=0 WHERE id=?",
            (titulo, descripcion, categoria, prioridad, vencimiento, id_),
        )
        self.con.commit()

    def alternar(self, id_):
        self.con.execute(
            "UPDATE tareas SET completada = 1 - completada WHERE id = ?", (id_,)
        )
        self.con.commit()

    def eliminar(self, id_):
        self.con.execute("DELETE FROM tareas WHERE id = ?", (id_,))
        self.con.commit()

    def por_avisar(self):
        ahora = datetime.now().strftime(DATE_FMT)
        return self.con.execute(
            "SELECT * FROM tareas WHERE completada = 0 AND avisada = 0"
            " AND vencimiento != '' AND vencimiento <= ?",
            (ahora,),
        ).fetchall()

    def marcar_avisada(self, id_):
        self.con.execute("UPDATE tareas SET avisada = 1 WHERE id = ?", (id_,))
        self.con.commit()

    def estadisticas(self):
        fila = self.con.execute(
            "SELECT COUNT(*) total, SUM(completada) hechas FROM tareas"
        ).fetchone()
        total = fila["total"] or 0
        hechas = fila["hechas"] or 0
        return total, hechas, total - hechas

    def cerrar(self):
        self.con.close()


# --------------------------------------------------------------------------
# Notificaciones del sistema operativo
# --------------------------------------------------------------------------
def notificar(titulo: str, mensaje: str) -> bool:
    """Muestra una notificación nativa. Devuelve True si el SO la mostró."""
    sistema = platform.system()
    try:
        if sistema == "Darwin":
            script = (
                f'display notification "{_esc(mensaje)}" '
                f'with title "{_esc(titulo)}" sound name "Glass"'
            )
            subprocess.run(["osascript", "-e", script], check=True, timeout=5)
            return True
        if sistema == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", titulo, mensaje], check=True, timeout=5)
            return True
        if sistema == "Windows":
            ps = (
                "[void][Windows.UI.Notifications.ToastNotificationManager,"
                "Windows.UI.Notifications,ContentType=WindowsRuntime];"
                "$t=[Windows.UI.Notifications.ToastNotificationManager]::"
                "GetTemplateContent('ToastText02');"
                "$n=$t.GetElementsByTagName('text');"
                f"$n.Item(0).AppendChild($t.CreateTextNode('{_esc(titulo)}'))>$null;"
                f"$n.Item(1).AppendChild($t.CreateTextNode('{_esc(mensaje)}'))>$null;"
                "$toast=[Windows.UI.Notifications.ToastNotification]::new($t);"
                "[Windows.UI.Notifications.ToastNotificationManager]::"
                f"CreateToastNotifier('{APP_NAME}').Show($toast)"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                check=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
    except Exception:
        pass
    return False  # el llamador usa un cuadro de diálogo como respaldo


def _esc(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace('"', "'").replace("\n", " ")


# --------------------------------------------------------------------------
# Diálogo para crear / editar tareas
# --------------------------------------------------------------------------
class DialogoTarea(tk.Toplevel):
    def __init__(self, padre, tarea=None):
        super().__init__(padre)
        self.title("Editar tarea" if tarea else "Nueva tarea")
        self.resizable(False, False)
        self.transient(padre)
        self.resultado = None

        marco = ttk.Frame(self, padding=14)
        marco.grid(sticky="nsew")

        self.v_titulo = tk.StringVar(value=tarea["titulo"] if tarea else "")
        self.v_cat = tk.StringVar(value=tarea["categoria"] if tarea else CATEGORIAS[0])
        self.v_pri = tk.StringVar(value=tarea["prioridad"] if tarea else "Media")
        self.v_venc = tk.StringVar(value=tarea["vencimiento"] if tarea else "")

        ttk.Label(marco, text="Título *").grid(row=0, column=0, sticky="w", pady=4)
        e_titulo = ttk.Entry(marco, textvariable=self.v_titulo, width=42)
        e_titulo.grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)

        ttk.Label(marco, text="Categoría").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(marco, textvariable=self.v_cat, values=CATEGORIAS,
                     state="readonly", width=16).grid(row=1, column=1, sticky="w")
        ttk.Label(marco, text="Prioridad").grid(row=1, column=2, sticky="e", padx=(10, 4))
        ttk.Combobox(marco, textvariable=self.v_pri, values=PRIORIDADES,
                     state="readonly", width=10).grid(row=1, column=3, sticky="w")

        ttk.Label(marco, text="Vence").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(marco, textvariable=self.v_venc, width=20).grid(row=2, column=1, sticky="w")
        ttk.Label(marco, text="AAAA-MM-DD HH:MM (opcional)",
                  foreground="gray").grid(row=2, column=2, columnspan=2, sticky="w", padx=(10, 0))

        ttk.Label(marco, text="Descripción").grid(row=3, column=0, sticky="nw", pady=4)
        self.txt = tk.Text(marco, width=42, height=6, wrap="word", relief="solid", bd=1)
        self.txt.grid(row=3, column=1, columnspan=3, sticky="ew", pady=4)
        if tarea:
            self.txt.insert("1.0", tarea["descripcion"] or "")

        botones = ttk.Frame(marco)
        botones.grid(row=4, column=0, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(botones, text="Cancelar", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(botones, text="Guardar", command=self._guardar).pack(side="right")

        self.bind("<Return>", lambda e: self._guardar() if e.widget is not self.txt else None)
        self.bind("<Escape>", lambda e: self.destroy())
        e_titulo.focus_set()
        self.grab_set()
        self.update_idletasks()
        x = padre.winfo_rootx() + (padre.winfo_width() - self.winfo_width()) // 2
        y = padre.winfo_rooty() + (padre.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _guardar(self):
        titulo = self.v_titulo.get().strip()
        venc = self.v_venc.get().strip()
        if not titulo:
            messagebox.showwarning("Dato requerido", "Escribe un título.", parent=self)
            return
        if venc:
            try:
                datetime.strptime(venc, DATE_FMT)
            except ValueError:
                messagebox.showwarning(
                    "Fecha no válida",
                    "Usa el formato AAAA-MM-DD HH:MM\nEjemplo: 2026-12-15 18:30",
                    parent=self,
                )
                return
        self.resultado = (
            titulo,
            self.txt.get("1.0", "end").strip(),
            self.v_cat.get(),
            self.v_pri.get(),
            venc,
        )
        self.destroy()


# --------------------------------------------------------------------------
# Ventana principal
# --------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self, ruta_db=None):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("920x560")
        self.minsize(760, 440)

        self.db = Base(ruta_db or os.path.join(carpeta_datos(), "agenda.db"))
        self.oscuro = False

        self._aplicar_tema_nativo()
        self._crear_menu()
        self._crear_interfaz()
        self._atajos()

        self.refrescar()
        self.after(1500, self._revisar_recordatorios)
        self.protocol("WM_DELETE_WINDOW", self._salir)

    # ---------- apariencia ----------
    def _aplicar_tema_nativo(self):
        estilo = ttk.Style(self)
        preferidos = {"Windows": "vista", "Darwin": "aqua"}.get(platform.system(), "clam")
        if preferidos in estilo.theme_names():
            estilo.theme_use(preferidos)
        self.estilo = estilo
        self.tema_nativo = estilo.theme_use()

    def _alternar_tema(self):
        self.oscuro = not self.oscuro
        if self.oscuro:
            self.estilo.theme_use("clam")
            fondo, texto, campo, sel = "#1e1f26", "#e8e8ee", "#2b2d36", "#3b6fd4"
        else:
            self.estilo.theme_use(self.tema_nativo)
            fondo, texto, campo, sel = "#f0f0f0", "#1a1a1a", "#ffffff", "#3b6fd4"
        self.configure(bg=fondo)
        e = self.estilo
        e.configure(".", background=fondo, foreground=texto, fieldbackground=campo)
        e.configure("Treeview", background=campo, fieldbackground=campo, foreground=texto)
        e.map("Treeview", background=[("selected", sel)], foreground=[("selected", "#ffffff")])
        e.configure("TCombobox", fieldbackground=campo, foreground=texto)
        e.map("TCombobox", fieldbackground=[("readonly", campo)],
              foreground=[("readonly", texto)], selectbackground=[("readonly", campo)],
              selectforeground=[("readonly", texto)])
        self._colorear_filas()

    # ---------- menú nativo ----------
    def _crear_menu(self):
        barra = tk.Menu(self)
        self.config(menu=barra)
        mod = "Command" if platform.system() == "Darwin" else "Ctrl"

        m_arch = tk.Menu(barra, tearoff=False)
        m_arch.add_command(label="Nueva tarea", accelerator=f"{mod}+N", command=self.nueva)
        m_arch.add_separator()
        m_arch.add_command(label="Exportar a CSV…", accelerator=f"{mod}+E", command=self.exportar_csv)
        m_arch.add_command(label="Importar desde CSV…", command=self.importar_csv)
        m_arch.add_separator()
        m_arch.add_command(label="Salir", accelerator=f"{mod}+Q", command=self._salir)
        barra.add_cascade(label="Archivo", menu=m_arch)

        m_edit = tk.Menu(barra, tearoff=False)
        m_edit.add_command(label="Editar tarea", accelerator="Enter", command=self.editar)
        m_edit.add_command(label="Completar / reabrir", accelerator="Espacio", command=self.alternar)
        m_edit.add_command(label="Copiar al portapapeles", accelerator=f"{mod}+C", command=self.copiar)
        m_edit.add_separator()
        m_edit.add_command(label="Eliminar", accelerator="Supr", command=self.eliminar)
        barra.add_cascade(label="Edición", menu=m_edit)

        m_ver = tk.Menu(barra, tearoff=False)
        m_ver.add_command(label="Buscar", accelerator=f"{mod}+F", command=lambda: self.e_buscar.focus_set())
        m_ver.add_command(label="Tema claro / oscuro", accelerator=f"{mod}+T", command=self._alternar_tema)
        barra.add_cascade(label="Ver", menu=m_ver)

        m_ayuda = tk.Menu(barra, tearoff=False)
        m_ayuda.add_command(label="Información del sistema", command=self.info_sistema)
        m_ayuda.add_command(label="Probar notificación", command=self.probar_notificacion)
        m_ayuda.add_separator()
        m_ayuda.add_command(label=f"Acerca de {APP_NAME}", command=self.acerca_de)
        barra.add_cascade(label="Ayuda", menu=m_ayuda)

    # ---------- interfaz ----------
    def _crear_interfaz(self):
        sup = ttk.Frame(self, padding=(10, 10, 10, 4))
        sup.pack(fill="x")
        ttk.Button(sup, text="+ Nueva", command=self.nueva).pack(side="left")
        ttk.Button(sup, text="Editar", command=self.editar).pack(side="left", padx=4)
        ttk.Button(sup, text="Completar", command=self.alternar).pack(side="left")
        ttk.Button(sup, text="Eliminar", command=self.eliminar).pack(side="left", padx=4)

        self.v_estado = tk.StringVar(value="Todas")
        cb = ttk.Combobox(sup, textvariable=self.v_estado, state="readonly", width=12,
                          values=["Todas", "Pendientes", "Completadas"])
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda e: self.refrescar())
        self.v_buscar = tk.StringVar()
        self.v_buscar.trace_add("write", lambda *a: self.refrescar())
        self.e_buscar = ttk.Entry(sup, textvariable=self.v_buscar, width=24)
        self.e_buscar.pack(side="right", padx=8)
        ttk.Label(sup, text="Buscar:").pack(side="right")

        # Las barras inferiores se empaquetan antes que la tabla para que
        # siempre queden visibles aunque la ventana sea pequeña.
        self.v_barra = tk.StringVar()
        ttk.Label(self, textvariable=self.v_barra, relief="sunken", anchor="w",
                  padding=(8, 2)).pack(fill="x", side="bottom")
        self.v_detalle = tk.StringVar(value="Selecciona una tarea para ver su descripción.")
        ttk.Label(self, textvariable=self.v_detalle, wraplength=880, padding=(12, 4),
                  anchor="w", justify="left").pack(fill="x", side="bottom")

        cuerpo = ttk.Frame(self, padding=(10, 0, 10, 4))
        cuerpo.pack(fill="both", expand=True)
        cols = ("titulo", "categoria", "prioridad", "vence", "estado")
        self.tabla = ttk.Treeview(cuerpo, columns=cols, show="headings", selectmode="browse")
        for c, t, w in [("titulo", "Tarea", 320), ("categoria", "Categoría", 110),
                        ("prioridad", "Prioridad", 90), ("vence", "Vence", 140),
                        ("estado", "Estado", 100)]:
            self.tabla.heading(c, text=t)
            self.tabla.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(cuerpo, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=sb.set)
        self.tabla.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tabla.bind("<Double-1>", lambda e: self.editar())
        self.tabla.bind("<<TreeviewSelect>>", lambda e: self._mostrar_detalle())


    def _atajos(self):
        cmd = "Command" if platform.system() == "Darwin" else "Control"
        self.bind_all(f"<{cmd}-n>", lambda e: self.nueva())
        self.bind_all(f"<{cmd}-e>", lambda e: self.exportar_csv())
        self.bind_all(f"<{cmd}-f>", lambda e: self.e_buscar.focus_set())
        self.bind_all(f"<{cmd}-t>", lambda e: self._alternar_tema())
        self.bind_all(f"<{cmd}-q>", lambda e: self._salir())
        self.tabla.bind(f"<{cmd}-c>", lambda e: self.copiar())
        self.tabla.bind("<Delete>", lambda e: self.eliminar())
        self.tabla.bind("<Return>", lambda e: self.editar())
        self.tabla.bind("<space>", lambda e: self.alternar())

    # ---------- datos en pantalla ----------
    def refrescar(self, seleccionar=None):
        self.tabla.delete(*self.tabla.get_children())
        for t in self.db.listar(self.v_buscar.get().strip(), self.v_estado.get()):
            estado = "Completada" if t["completada"] else (
                "Vencida" if self._vencida(t) else "Pendiente")
            self.tabla.insert("", "end", iid=str(t["id"]), values=(
                t["titulo"], t["categoria"], t["prioridad"],
                t["vencimiento"] or "—", estado))
        self._colorear_filas()
        if seleccionar and self.tabla.exists(str(seleccionar)):
            self.tabla.selection_set(str(seleccionar))
        total, hechas, pend = self.db.estadisticas()
        self.v_barra.set(
            f"{total} tareas · {pend} pendientes · {hechas} completadas   |   "
            f"BD local: {self.db.ruta}")
        self._mostrar_detalle()

    def _colorear_filas(self):
        claro = not self.oscuro
        self.tabla.tag_configure("Completada", foreground="#7a7a7a")
        self.tabla.tag_configure("Vencida", foreground="#c0392b" if claro else "#ff8a80")
        for iid in self.tabla.get_children():
            estado = self.tabla.set(iid, "estado")
            self.tabla.item(iid, tags=(estado,))

    @staticmethod
    def _vencida(t):
        return bool(t["vencimiento"]) and not t["completada"] and \
            t["vencimiento"] < datetime.now().strftime(DATE_FMT)

    def _id_seleccionado(self):
        sel = self.tabla.selection()
        return int(sel[0]) if sel else None

    def _mostrar_detalle(self):
        id_ = self._id_seleccionado()
        if id_ is None:
            self.v_detalle.set("Selecciona una tarea para ver su descripción.")
            return
        t = self.db.obtener(id_)
        if t:
            self.v_detalle.set(f"{t['titulo']}: {t['descripcion'] or '(sin descripción)'}")

    # ---------- acciones ----------
    def nueva(self):
        dlg = DialogoTarea(self)
        self.wait_window(dlg)
        if dlg.resultado:
            nuevo = self.db.insertar(*dlg.resultado)
            self.refrescar(nuevo)

    def editar(self):
        id_ = self._id_seleccionado()
        if id_ is None:
            return
        dlg = DialogoTarea(self, self.db.obtener(id_))
        self.wait_window(dlg)
        if dlg.resultado:
            self.db.actualizar(id_, *dlg.resultado)
            self.refrescar(id_)

    def alternar(self):
        id_ = self._id_seleccionado()
        if id_ is not None:
            self.db.alternar(id_)
            self.refrescar(id_)

    def eliminar(self):
        id_ = self._id_seleccionado()
        if id_ is None:
            return
        t = self.db.obtener(id_)
        if messagebox.askyesno("Eliminar", f"¿Eliminar «{t['titulo']}»?", parent=self):
            self.db.eliminar(id_)
            self.refrescar()

    def copiar(self):
        id_ = self._id_seleccionado()
        if id_ is None:
            return
        t = self.db.obtener(id_)
        texto = (f"{t['titulo']} [{t['categoria']} · {t['prioridad']}]"
                 f" vence: {t['vencimiento'] or 'sin fecha'}\n{t['descripcion']}")
        self.clipboard_clear()
        self.clipboard_append(texto)
        self.v_barra.set("Tarea copiada al portapapeles del sistema.")

    # ---------- sistema de archivos ----------
    def exportar_csv(self):
        ruta = filedialog.asksaveasfilename(
            parent=self, title="Exportar tareas", defaultextension=".csv",
            initialfile=f"tareas_{datetime.now():%Y%m%d}.csv",
            filetypes=[("CSV", "*.csv"), ("Todos los archivos", "*.*")])
        if not ruta:
            return
        try:
            with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["titulo", "descripcion", "categoria", "prioridad",
                            "vencimiento", "completada"])
                for t in self.db.listar():
                    w.writerow([t["titulo"], t["descripcion"], t["categoria"],
                                t["prioridad"], t["vencimiento"], t["completada"]])
            messagebox.showinfo("Exportación lista", f"Archivo guardado en:\n{ruta}", parent=self)
        except OSError as e:
            messagebox.showerror("Error", f"No se pudo escribir el archivo:\n{e}", parent=self)

    def importar_csv(self):
        ruta = filedialog.askopenfilename(
            parent=self, title="Importar tareas",
            filetypes=[("CSV", "*.csv"), ("Todos los archivos", "*.*")])
        if not ruta:
            return
        cont = 0
        try:
            with open(ruta, newline="", encoding="utf-8-sig") as f:
                for fila in csv.DictReader(f):
                    titulo = (fila.get("titulo") or "").strip()
                    if not titulo:
                        continue
                    venc = (fila.get("vencimiento") or "").strip()
                    try:
                        if venc:
                            datetime.strptime(venc, DATE_FMT)
                    except ValueError:
                        venc = ""
                    cat = fila.get("categoria") or "Otros"
                    pri = fila.get("prioridad") or "Media"
                    nuevo = self.db.insertar(
                        titulo, fila.get("descripcion", ""),
                        cat if cat in CATEGORIAS else "Otros",
                        pri if pri in PRIORIDADES else "Media", venc)
                    if str(fila.get("completada", "0")).strip() == "1":
                        self.db.alternar(nuevo)
                    cont += 1
        except (OSError, csv.Error, UnicodeDecodeError) as e:
            messagebox.showerror("Error", f"No se pudo leer el archivo:\n{e}", parent=self)
            return
        self.refrescar()
        messagebox.showinfo("Importación lista", f"Se importaron {cont} tareas.", parent=self)

    # ---------- recordatorios y notificaciones ----------
    def _revisar_recordatorios(self):
        for t in self.db.por_avisar():
            self._avisar(t)
            self.db.marcar_avisada(t["id"])
        self.refrescar(self._id_seleccionado())
        self.after(CHECK_INTERVAL_MS, self._revisar_recordatorios)

    def _avisar(self, t):
        titulo = "Recordatorio de tarea"
        cuerpo = f"{t['titulo']} (vence {t['vencimiento']})"
        if not notificar(titulo, cuerpo):
            self.bell()
            messagebox.showinfo(titulo, cuerpo, parent=self)

    def probar_notificacion(self):
        ok = notificar(APP_NAME, "Así se ven los avisos del sistema operativo.")
        if not ok:
            self.bell()
            messagebox.showinfo(
                APP_NAME,
                "Este equipo no ofrece notificaciones por línea de comandos.\n"
                "Se usa un cuadro de diálogo como respaldo.", parent=self)

    # ---------- acceso a información del equipo ----------
    def info_sistema(self):
        datos = [
            ("Sistema operativo", f"{platform.system()} {platform.release()}"),
            ("Versión", platform.version()[:60]),
            ("Arquitectura", platform.machine()),
            ("Python", platform.python_version()),
            ("Tema de interfaz", self.tema_nativo),
            ("Resolución de pantalla", f"{self.winfo_screenwidth()} x {self.winfo_screenheight()}"),
            ("Usuario del sistema", os.environ.get("USERNAME") or os.environ.get("USER", "?")),
            ("Carpeta de datos", carpeta_datos()),
            ("Base de datos", self.db.ruta),
        ]
        messagebox.showinfo("Información del sistema",
                            "\n".join(f"{k}: {v}" for k, v in datos), parent=self)

    def acerca_de(self):
        messagebox.showinfo(
            f"Acerca de {APP_NAME}",
            f"{APP_NAME} {APP_VERSION}\nAplicación nativa de escritorio.\n\n"
            "Python + Tkinter + SQLite\nUniversidad Tecnológica de Puebla", parent=self)

    def _salir(self):
        self.db.cerrar()
        self.destroy()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    sys.exit(main())