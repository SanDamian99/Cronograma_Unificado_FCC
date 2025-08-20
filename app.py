import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import time
from supabase import create_client, Client

# --- Configuración de la Página ---
st.set_page_config(
    page_title="Cronograma Posgrados",
    page_icon="🗓️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Estilos CSS ---
st.markdown("""
<style>
    /* Colores base */
    .stApp {
        background-color: #0E1117; /* Azul oscuro de fondo */
        color: #FFFFFF; /* Texto blanco */
    }
    /* Títulos y encabezados */
    h1, h2, h3 {
        color: #D4AF37; /* Dorado para títulos */
    }
    /* Botones */
    .stButton>button {
        background-color: #D4AF37;
        color: #0E1117;
        border-radius: 8px;
        border: 2px solid #D4AF37;
    }
    .stButton>button:hover {
        background-color: #FFFFFF;
        color: #D4AF37;
    }
    /* Widgets y tablas */
    .stTextInput>div>div>input, .stSelectbox>div>div>select, .stNumberInput>div>div>input, .stDateInput>div>div>input {
        background-color: #262730;
        color: #FFFFFF;
    }
    /* Contenedores y expanders */
    .stExpander, .stContainer {
        border: 1px solid #D4AF37;
        border-radius: 10px;
        padding: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# --- Conexión a Supabase ---
@st.cache_resource
def init_connection():
    """Inicializa la conexión a Supabase usando las credenciales de st.secrets."""
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase: Client = init_connection()

# --- Funciones de Base de Datos ---
@st.cache_data(ttl=60) # Cache para no recargar constantemente
def load_data_from_supabase():
    """Carga los datos desde la tabla 'cronograma' en Supabase."""
    response = supabase.table('cronograma').select('*').execute()
    df = pd.DataFrame(response.data)
    if not df.empty:
        # Convertir columnas de tiempo de string a objeto time
        df['Hora de inicio'] = pd.to_datetime(df['Hora de inicio'], format='%H:%M:%S').dt.time
        df['Hora de finalizacion'] = pd.to_datetime(df['Hora de finalizacion'], format='%H:%M:%S').dt.time
    return df

# Inicializar estado de sesión con datos de Supabase
if 'schedule_df' not in st.session_state:
    st.session_state.schedule_df = load_data_from_supabase()

# --- Funciones Auxiliares ---
def check_conflicts(new_class, existing_df):
    """Verifica si una nueva clase genera conflictos en el horario existente."""
    conflicts = []
    for _, row in new_class.iterrows():
        # Conflicto para el profesor
        prof_conflict = existing_df[
            (existing_df['Profesor'] == row['Profesor']) &
            (existing_df['Día'] == row['Día']) &
            (existing_df['Hora de inicio'] < row['Hora de finalizacion']) &
            (existing_df['Hora de finalizacion'] > row['Hora de inicio'])
        ]
        if not prof_conflict.empty:
            info = prof_conflict.iloc[0]
            conflicts.append(f"❌ **Cruce de Profesor:** {row['Profesor']} ya tiene la clase '{info['Nombre de la clase']}' ({info['ID']}) el {row['Día']} de {info['Hora de inicio'].strftime('%H:%M')} a {info['Hora de finalizacion'].strftime('%H:%M')}.")

        # Conflicto para el programa/semestre (si no es simultánea)
        if not row['Simultaneo']:
            student_conflict = existing_df[
                (existing_df['Programa'] == row['Programa']) &
                (existing_df['Semestre'] == row['Semestre']) &
                (existing_df['Día'] == row['Día']) &
                (existing_df['Hora de inicio'] < row['Hora de finalizacion']) &
                (existing_df['Hora de finalizacion'] > row['Hora de inicio']) &
                (existing_df['Simultaneo'] == False)
            ]
            if not student_conflict.empty:
                info = student_conflict.iloc[0]
                conflicts.append(f"❌ **Cruce de Estudiantes:** El programa {row['Programa']} (Sem {row['Semestre']}) ya tiene la clase '{info['Nombre de la clase']}' ({info['ID']}) el {row['Día']} de {info['Hora de inicio'].strftime('%H:%M')} a {info['Hora de finalizacion'].strftime('%H:%M')}.")
    return conflicts

def format_time_for_display(df):
    """Formatea las columnas de tiempo a string HH:MM para una mejor visualización."""
    df_display = df.copy()
    for col in ['Hora de inicio', 'Hora de finalizacion']:
        if col in df_display.columns:
            df_display[col] = df_display[col].apply(lambda x: x.strftime('%H:%M') if pd.notnull(x) else '')
    return df_display

# --- Interfaz de Usuario (UI) ---
st.title("🗓️ Organizador de Cronogramas de Posgrado")
st.markdown("---")

with st.expander("ℹ️ ¿Cómo funciona esta aplicación?", expanded=True):
    st.write("""
    Esta herramienta está diseñada para simplificar la creación y gestión de los horarios de clase de los posgrados. La información se guarda de forma segura y persistente en una base de datos en la nube (Supabase).

    1.  **Añadir una Clase:** Utiliza el formulario para ingresar la información de una materia **Regular** o **Modular**.
    2.  **Validación Automática:** Al añadir, el sistema revisa que no existan cruces para profesores o estudiantes.
    3.  **Gestión del Cronograma:** Filtra, visualiza en la tabla o en el calendario, y descarga los datos en CSV.
    4.  **Eliminar:** Usa la sección de eliminación para borrar una clase y todas sus sesiones del cronograma.
    """)
st.markdown("---")

# --- Barra Lateral: Filtros y Opciones ---
st.sidebar.header("Filtros y Opciones")

# Obtener opciones únicas para los filtros
if not st.session_state.schedule_df.empty:
    programas = st.session_state.schedule_df['Programa'].unique()
    profesores = st.session_state.schedule_df['Profesor'].unique()
    semestres = st.session_state.schedule_df['Semestre'].unique()
else:
    programas, profesores, semestres = [], [], []

# Filtros
programa_filtro = st.sidebar.multiselect("Filtrar por Programa", options=programas)
profesor_filtro = st.sidebar.multiselect("Filtrar por Profesor", options=profesores)
semestre_filtro = st.sidebar.multiselect("Filtrar por Semestre", options=semestres)

# Aplicar filtros
filtered_df = st.session_state.schedule_df.copy()
if programa_filtro:
    filtered_df = filtered_df[filtered_df['Programa'].isin(programa_filtro)]
if profesor_filtro:
    filtered_df = filtered_df[filtered_df['Profesor'].isin(profesor_filtro)]
if semestre_filtro:
    filtered_df = filtered_df[filtered_df['Semestre'].isin(semestre_filtro)]

# --- Formulario para Añadir Clases ---
st.header("➕ Añadir Nueva Clase")

tipo_clase = st.radio("Tipo de Clase", ["Regular", "Modular"], horizontal=True)

with st.form("new_class_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        descripcion = st.text_input("Descripción")
        catalogo = st.text_input("# de Catalogo")
        nombre_clase = st.text_input("Nombre de la clase")
        programa = st.text_input("Programa (Ej: Maestría en Psicología Clínica)")
        semestre = st.number_input("Semestre", min_value=1, step=1, format="%d")
        creditos = st.number_input("Creditos", min_value=1, step=1, format="%d")

    with col2:
        horas = st.number_input("Horas totales", min_value=1, step=1, format="%d")
        simultaneo = st.checkbox("¿Permite Simultaneidad?")
        num_sesiones = st.number_input("Número de sesiones/módulos", min_value=1, step=1, format="%d")

    st.markdown("---")
    st.subheader("Detalles de las Sesiones")
    
    sesiones_data = []
    
    if tipo_clase == "Regular":
        st.write("**Clase Regular:** Todas las sesiones tienen el mismo profesor y horario.")
        profesor = st.text_input("Profesor Asignado")
        dia = st.selectbox("Día de la semana", ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"])
        hora_inicio = st.time_input("Hora de Inicio", value=time(8, 0))
        hora_fin = st.time_input("Hora de Finalización", value=time(10, 0))

        for i in range(num_sesiones):
            sesiones_data.append({"profesor": profesor, "dia": dia, "hora_inicio": hora_inicio, "hora_fin": hora_fin})
            
    else: # Modular
        st.write("**Clase Modular:** Define un profesor y horario para cada módulo.")
        for i in range(num_sesiones):
            st.markdown(f"**Módulo {i+1}**")
            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            profesor = m_col1.text_input(f"Profesor Módulo {i+1}", key=f"prof_{i}")
            dia = m_col2.selectbox(f"Día Módulo {i+1}", ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"], key=f"dia_{i}")
            hora_inicio = m_col3.time_input(f"Inicio Módulo {i+1}", value=time(8, 0), key=f"start_{i}")
            hora_fin = m_col4.time_input(f"Fin Módulo {i+1}", value=time(10, 0), key=f"end_{i}")
            sesiones_data.append({"profesor": profesor, "dia": dia, "hora_inicio": hora_inicio, "hora_fin": hora_fin})

    submit_button = st.form_submit_button("Añadir Clase al Cronograma")

# --- Lógica de Procesamiento del Formulario ---
if submit_button:
    if any(s['hora_fin'] <= s['hora_inicio'] for s in sesiones_data):
        st.error("Error: La hora de finalización debe ser posterior a la hora de inicio para todas las sesiones.")
    else:
        new_class_records = []
        class_id_base = f"{catalogo}-{nombre_clase.replace(' ', '')[:5]}"
        for i, sesion in enumerate(sesiones_data):
            new_class_records.append({
                'ID': f"{class_id_base}-S{i+1}", 'Descripción': descripcion, '# de Catalogo': catalogo, 
                'Nombre de la clase': nombre_clase, 'Programa': programa, 'Semestre': int(semestre), 
                'Creditos': int(creditos), 'Horas': int(horas), 'Profesor': sesion['profesor'], 
                'Simultaneo': simultaneo, 'Numero de sesiones': int(num_sesiones), 'Sesión': i + 1, 
                'Día': sesion['dia'], 'Hora de inicio': sesion['hora_inicio'], 'Hora de finalizacion': sesion['hora_fin']
            })
        
        temp_df = pd.DataFrame(new_class_records)
        conflictos = check_conflicts(temp_df, st.session_state.schedule_df)

        if conflictos:
            st.error("No se pudo añadir la clase debido a conflictos:")
            for c in conflictos:
                st.warning(c)
        else:
            temp_df_insert = temp_df.copy()
            temp_df_insert['Hora de inicio'] = temp_df_insert['Hora de inicio'].astype(str)
            temp_df_insert['Hora de finalizacion'] = temp_df_insert['Hora de finalizacion'].astype(str)
            records_to_insert = temp_df_insert.to_dict('records')
            
            try:
                supabase.table('cronograma').insert(records_to_insert).execute()
                st.success(f"¡Clase '{nombre_clase}' añadida exitosamente a la base de datos!")
                st.cache_data.clear()
                st.session_state.schedule_df = load_data_from_supabase()
                st.rerun()
            except Exception as e:
                st.error(f"Error al guardar en la base de datos: {e}")

# --- Visualización del Cronograma ---
st.markdown("---")
st.header("📅 Cronograma General de Clases")

if st.session_state.schedule_df.empty:
    st.info("Aún no se han añadido clases al cronograma.")
else:
    st.dataframe(format_time_for_display(filtered_df), use_container_width=True)
    csv_completo = st.session_state.schedule_df.to_csv(index=False).encode('utf-8')
    csv_filtrado = filtered_df.to_csv(index=False).encode('utf-8')
    col_desc1, col_desc2 = st.columns(2)
    col_desc1.download_button("📥 Descargar Cronograma Completo (CSV)", csv_completo, 'cronograma_completo.csv', 'text/csv')
    col_desc2.download_button("📥 Descargar Vista Filtrada (CSV)", csv_filtrado, 'cronograma_filtrado.csv', 'text/csv')

    # --- Visualización en Calendario ---
    st.markdown("---")
    st.header("🗓️ Vista de Calendario Semanal")
    if not filtered_df.empty:
        day_map = {"Lunes": 1, "Martes": 2, "Miércoles": 3, "Jueves": 4, "Viernes": 5, "Sábado": 6}
        calendar_df = filtered_df.copy()
        calendar_df['day_num'] = calendar_df['Día'].map(day_map)
        calendar_df = calendar_df.sort_values(by=['day_num', 'Hora de inicio'])
        
        fig = px.timeline(
            calendar_df, x_start="Hora de inicio", x_end="Hora de finalizacion", y="Día",
            color="Programa", text="Nombre de la clase", hover_data=['ID', 'Semestre', 'Profesor'],
            title="Distribución Semanal de Clases", category_orders={"Día": ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]}
        )
        fig.update_layout(
            xaxis_title="Hora del Día", yaxis_title="Día de la Semana", plot_bgcolor='#262730',
            paper_bgcolor='#0E1117', font_color='#FFFFFF', title_font_color='#D4AF37',
            legend_title_font_color='#D4AF37'
        )
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No hay datos para mostrar en el calendario con los filtros actuales.")

# --- Sección para Eliminar Clases ---
st.markdown("---")
st.header("🗑️ Eliminar Clase del Cronograma")

if not st.session_state.schedule_df.empty:
    with st.form("delete_form"):
        unique_class_ids = st.session_state.schedule_df['ID'].str.split('-S').str[0].unique()
        id_to_delete_base = st.selectbox("Selecciona el ID de la clase a eliminar", options=unique_class_ids)
        delete_button = st.form_submit_button("Eliminar Clase")

        if delete_button and id_to_delete_base:
            try:
                supabase.table('cronograma').delete().like('ID', f'{id_to_delete_base}%').execute()
                st.success(f"La clase '{id_to_delete_base}' y todas sus sesiones han sido eliminadas.")
                st.cache_data.clear()
                st.session_state.schedule_df = load_data_from_supabase()
                st.rerun()
            except Exception as e:
                st.error(f"Error al eliminar de la base de datos: {e}")
else:
    st.info("El cronograma está vacío, no hay clases para eliminar.")
