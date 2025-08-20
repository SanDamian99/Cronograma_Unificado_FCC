import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import time, date
from supabase import create_client, Client

# --- Configuración de la Página ---
st.set_page_config(
    page_title="Cronograma Posgrados",
    page_icon="🗓️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Estilos CSS (Sin cambios) ---
st.markdown("""
<style>
    /* ... (Tu CSS se mantiene igual) ... */
    .stApp { background-color: #0E1117; color: #FFFFFF; }
    h1, h2, h3 { color: #D4AF37; }
    .stButton>button { background-color: #D4AF37; color: #0E1117; border-radius: 8px; border: 2px solid #D4AF37; }
    .stButton>button:hover { background-color: #FFFFFF; color: #D4AF37; }
    .stTextInput>div>div>input, .stSelectbox>div>div>select, .stNumberInput>div>div>input, .stDateInput>div>div>input, .stTimeInput>div>div>input { background-color: #262730; color: #FFFFFF; }
    .stExpander, .stContainer { border: 1px solid #D4AF37; border-radius: 10px; padding: 1rem; }
</style>
""", unsafe_allow_html=True)

# --- Conexión a Supabase ---
@st.cache_resource
def init_connection():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase: Client = init_connection()

# --- Funciones de Base de Datos ---
@st.cache_data(ttl=60)
def load_data_from_supabase():
    response = supabase.table('cronograma').select('*').execute()
    df = pd.DataFrame(response.data)
    if not df.empty:
        # Asegurarse de que las columnas de fecha y hora se interpreten correctamente
        df['Fecha'] = pd.to_datetime(df['Fecha']).dt.date
        df['Hora de inicio'] = pd.to_datetime(df['Hora de inicio'], format='%H:%M:%S').dt.time
        df['Hora de finalizacion'] = pd.to_datetime(df['Hora de finalizacion'], format='%H:%M:%S').dt.time
    return df

if 'schedule_df' not in st.session_state:
    st.session_state.schedule_df = load_data_from_supabase()

# --- Funciones Auxiliares ---
def check_conflicts(new_class, existing_df):
    conflicts = []
    if existing_df.empty:
        return conflicts
        
    for _, row in new_class.iterrows():
        # Filtra el DF existente por la misma fecha para optimizar
        day_schedule = existing_df[existing_df['Fecha'] == row['Fecha']]
        if day_schedule.empty:
            continue

        # Conflicto para el profesor
        prof_conflict = day_schedule[
            (day_schedule['Profesor'] == row['Profesor']) &
            (day_schedule['Hora de inicio'] < row['Hora de finalizacion']) &
            (day_schedule['Hora de finalizacion'] > row['Hora de inicio'])
        ]
        if not prof_conflict.empty:
            info = prof_conflict.iloc[0]
            conflicts.append(f"❌ **Cruce de Profesor:** {row['Profesor']} ya tiene la clase '{info['Nombre de la clase']}' el {row['Fecha'].strftime('%Y-%m-%d')} de {info['Hora de inicio'].strftime('%H:%M')} a {info['Hora de finalizacion'].strftime('%H:%M')}.")

        # Conflicto para el programa/semestre
        if not row['Simultaneo']:
            student_conflict = day_schedule[
                (day_schedule['Programa'] == row['Programa']) &
                (day_schedule['Semestre'] == row['Semestre']) &
                (day_schedule['Hora de inicio'] < row['Hora de finalizacion']) &
                (day_schedule['Hora de finalizacion'] > row['Hora de inicio']) &
                (day_schedule['Simultaneo'] == False)
            ]
            if not student_conflict.empty:
                info = student_conflict.iloc[0]
                conflicts.append(f"❌ **Cruce de Estudiantes:** El programa {row['Programa']} ya tiene la clase '{info['Nombre de la clase']}' el {row['Fecha'].strftime('%Y-%m-%d')} de {info['Hora de inicio'].strftime('%H:%M')} a {info['Hora de finalizacion'].strftime('%H:%M')}.")
    return conflicts

def format_for_display(df):
    df_display = df.copy()
    if 'Fecha' in df_display.columns:
        df_display['Fecha'] = pd.to_datetime(df_display['Fecha']).dt.strftime('%Y-%m-%d')
    for col in ['Hora de inicio', 'Hora de finalizacion']:
        if col in df_display.columns:
            df_display[col] = df_display[col].apply(lambda x: x.strftime('%H:%M') if pd.notnull(x) else '')
    return df_display

# --- Interfaz de Usuario (UI) ---
st.title("🗓️ Organizador de Cronogramas de Posgrado")
st.markdown("---")

with st.expander("ℹ️ ¿Cómo funciona esta aplicación?", expanded=True):
    st.write("...") # Misma explicación que antes

# --- Barra Lateral: Filtros ---
# ... (Sin cambios en la lógica de filtros)

# --- Formulario para Añadir Clases ---
st.header("➕ Añadir Nueva Clase")

tipo_clase = st.radio("Tipo de Clase", ["Regular", "Modular"], horizontal=True)

with st.form("new_class_form", clear_on_submit=True):
    # --- Datos Generales de la Clase ---
    st.subheader("Datos Generales")
    col1, col2 = st.columns(2)
    with col1:
        descripcion = st.text_input("Descripción")
        catalogo = st.text_input("# de Catalogo")
        nombre_clase = st.text_input("Nombre de la clase")
        programa = st.text_input("Programa")
    with col2:
        semestre = st.number_input("Semestre", min_value=1, step=1, format="%d")
        creditos = st.number_input("Creditos", min_value=1, step=1, format="%d")
        horas = st.number_input("Horas totales", min_value=1, step=1, format="%d")
        simultaneo = st.checkbox("¿Permite Simultaneidad?")

    st.markdown("---")
    st.subheader("Detalles de las Sesiones")
    
    sesiones_data = []

    # --- LÓGICA PARA CLASE REGULAR (UN SOLO PROFESOR) ---
    if tipo_clase == "Regular":
        profesor_regular = st.text_input("Profesor Asignado para todas las sesiones")
        num_sesiones_regular = st.number_input("Número total de sesiones de la clase", min_value=1, step=1, format="%d")
        
        for i in range(num_sesiones_regular):
            st.markdown(f"**Sesión {i+1}**")
            s_col1, s_col2, s_col3 = st.columns(3)
            fecha = s_col1.date_input(f"Fecha Sesión {i+1}", key=f"reg_date_{i}")
            hora_inicio = s_col2.time_input(f"Inicio Sesión {i+1}", value=time(8, 0), key=f"reg_start_{i}")
            hora_fin = s_col3.time_input(f"Fin Sesión {i+1}", value=time(10, 0), key=f"reg_end_{i}")
            sesiones_data.append({"profesor": profesor_regular, "modulo": 1, "sesion_num": i+1, "fecha": fecha, "hora_inicio": hora_inicio, "hora_fin": hora_fin})

    # --- LÓGICA PARA CLASE MODULAR (MÚLTIPLES MÓDULOS Y PROFESORES) ---
    else: # Modular
        num_modulos = st.number_input("Número de Módulos", min_value=1, step=1, format="%d")
        sesion_counter = 1
        for i in range(num_modulos):
            with st.container():
                st.markdown(f"--- \n ### Módulo {i+1}")
                m_col1, m_col2 = st.columns(2)
                profesor_modulo = m_col1.text_input(f"Profesor del Módulo {i+1}", key=f"mod_prof_{i}")
                num_sesiones_modulo = m_col2.number_input(f"Número de sesiones para Módulo {i+1}", min_value=1, step=1, format="%d", key=f"mod_ses_num_{i}")

                for j in range(num_sesiones_modulo):
                    st.markdown(f"**Sesión {j+1} del Módulo {i+1}**")
                    ms_col1, ms_col2, ms_col3 = st.columns(3)
                    fecha = ms_col1.date_input(f"Fecha Sesión {j+1} (M{i+1})", key=f"mod_date_{i}_{j}")
                    hora_inicio = ms_col2.time_input(f"Inicio Sesión {j+1} (M{i+1})", value=time(8, 0), key=f"mod_start_{i}_{j}")
                    hora_fin = ms_col3.time_input(f"Fin Sesión {j+1} (M{i+1})", value=time(10, 0), key=f"mod_end_{i}_{j}")
                    sesiones_data.append({"profesor": profesor_modulo, "modulo": i+1, "sesion_num": sesion_counter, "fecha": fecha, "hora_inicio": hora_inicio, "hora_fin": hora_fin})
                    sesion_counter += 1
    
    submit_button = st.form_submit_button("Añadir Clase al Cronograma")

# --- Lógica de Procesamiento del Formulario ---
if submit_button:
    if any(s['hora_fin'] <= s['hora_inicio'] for s in sesiones_data):
        st.error("Error: La hora de finalización debe ser posterior a la hora de inicio para todas las sesiones.")
    else:
        new_class_records = []
        class_id_base = f"{catalogo}-{nombre_clase.replace(' ', '')[:5]}"
        for sesion in sesiones_data:
            new_class_records.append({
                'ID': f"{class_id_base}-S{sesion['sesion_num']}", 'Descripción': descripcion, '# de Catalogo': catalogo, 
                'Nombre de la clase': nombre_clase, 'Programa': programa, 'Semestre': int(semestre), 
                'Creditos': int(creditos), 'Horas': int(horas), 'Profesor': sesion['profesor'], 
                'Simultaneo': simultaneo, 'Módulo': sesion['modulo'], 'Sesión': sesion['sesion_num'], 
                'Fecha': sesion['fecha'], 'Hora de inicio': sesion['hora_inicio'], 'Hora de finalizacion': sesion['hora_fin']
            })
        
        temp_df = pd.DataFrame(new_class_records)
        conflictos = check_conflicts(temp_df, st.session_state.schedule_df)

        if conflictos:
            st.error("No se pudo añadir la clase debido a conflictos:")
            for c in conflictos:
                st.warning(c)
        else:
            temp_df_insert = temp_df.copy()
            temp_df_insert['Fecha'] = temp_df_insert['Fecha'].astype(str)
            temp_df_insert['Hora de inicio'] = temp_df_insert['Hora de inicio'].astype(str)
            temp_df_insert['Hora de finalizacion'] = temp_df_insert['Hora de finalizacion'].astype(str)
            records_to_insert = temp_df_insert.to_dict('records')
            
            try:
                supabase.table('cronograma').insert(records_to_insert).execute()
                st.success(f"¡Clase '{nombre_clase}' añadida exitosamente!")
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
    # Aplicar filtros
    filtered_df = st.session_state.schedule_df.copy()
    if programa_filtro:
        filtered_df = filtered_df[filtered_df['Programa'].isin(programa_filtro)]
    if profesor_filtro:
        filtered_df = filtered_df[filtered_df['Profesor'].isin(profesor_filtro)]
    if semestre_filtro:
        filtered_df = filtered_df[filtered_df['Semestre'].isin(semestre_filtro)]
    
    st.dataframe(format_for_display(filtered_df), use_container_width=True)
    # ... (Botones de descarga sin cambios)

    # --- Visualización en Calendario (Mejorada) ---
    st.markdown("---")
    st.header("🗓️ Vista de Calendario")
    if not filtered_df.empty:
        calendar_df = filtered_df.copy()
        # Crear columnas de datetime para el inicio y fin
        calendar_df['start'] = calendar_df.apply(lambda row: pd.to_datetime(f"{row['Fecha']} {row['Hora de inicio']}"), axis=1)
        calendar_df['end'] = calendar_df.apply(lambda row: pd.to_datetime(f"{row['Fecha']} {row['Hora de finalizacion']}"), axis=1)
        
        fig = px.timeline(
            calendar_df, x_start="start", x_end="end", y="Programa",
            color="Profesor", text="Nombre de la clase", 
            hover_data=['ID', 'Semestre', 'Módulo', 'Fecha'],
            title="Cronograma de Clases por Programa y Profesor"
        )
        fig.update_layout(
            xaxis_title="Fecha y Hora", yaxis_title="Programa", plot_bgcolor='#262730',
            paper_bgcolor='#0E1117', font_color='#FFFFFF', title_font_color='#D4AF37',
            legend_title_font_color='#D4AF37'
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No hay datos para mostrar en el calendario con los filtros actuales.")

# --- Sección para Eliminar Clases (Sin cambios en la lógica) ---
# ...
