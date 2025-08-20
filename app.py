import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import time, date, datetime
from supabase import create_client, Client
import math
import itertools

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
    .stApp {
        background-color: #0E1117; color: #FFFFFF;
    }
    h1, h2, h3 {
        color: #D4AF37;
    }
    .stButton>button {
        background-color: #D4AF37; color: #0E1117; border-radius: 8px; border: 2px solid #D4AF37;
    }
    .stButton>button:hover {
        background-color: #FFFFFF; color: #D4AF37;
    }
    .stTextInput>div>div>input, .stSelectbox>div>div>select, .stNumberInput>div>div>input, .stDateInput>div>div>input, .stTimeInput>div>div>input {
        background-color: #262730; color: #FFFFFF;
    }
    .stExpander, .stContainer {
        border: 1px solid #D4AF37; border-radius: 10px; padding: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# --- Conexión a Supabase y Carga de Datos ---
@st.cache_resource
def init_connection():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase: Client = init_connection()

@st.cache_data(ttl=60)
def load_data_from_supabase():
    response = supabase.table('cronograma').select('*').execute()
    df = pd.DataFrame(response.data)
    if not df.empty:
        df['Fecha'] = pd.to_datetime(df['Fecha']).dt.date
        df['Hora de inicio'] = pd.to_datetime(df['Hora de inicio'], format='%H:%M:%S').dt.time
        df['Hora de finalizacion'] = pd.to_datetime(df['Hora de finalizacion'], format='%H:%M:%S').dt.time
    return df

@st.cache_data(ttl=300)
def get_unique_values(column_name):
    """Obtiene valores únicos de una columna para los selectbox."""
    response = supabase.table('cronograma').select(column_name).execute()
    if response.data:
        return sorted(list(set(item[column_name] for item in response.data)))
    return []

if 'schedule_df' not in st.session_state:
    st.session_state.schedule_df = load_data_from_supabase()

# --- Funciones de Validación ---
def check_self_overlap(df):
    """Revisa si las sesiones en un DataFrame se cruzan entre ellas."""
    conflicts = []
    for (idx1, row1), (idx2, row2) in itertools.combinations(df.iterrows(), 2):
        if row1['Fecha'] == row2['Fecha']:
            # Comprobar si los intervalos de tiempo se solapan
            if row1['Hora de inicio'] < row2['Hora de finalizacion'] and row2['Hora de inicio'] < row1['Hora de finalizacion']:
                conflicts.append(f"🔥 **Cruce Interno:** La sesión {idx1+1} y la sesión {idx2+1} se solapan el mismo día ({row1['Fecha']}).")
    return conflicts

def check_db_conflicts(new_class, existing_df):
    """Revisa conflictos contra la base de datos existente."""
    conflicts = []
    if existing_df.empty:
        return conflicts
    for _, row in new_class.iterrows():
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
            conflicts.append(f"❌ **Cruce de Profesor:** El profesor **{row['Profesor']}** ya tiene la clase **'{info['Nombre de la clase']}'** ({info['ID']}) programada el **{row['Fecha'].strftime('%Y-%m-%d')}** de {info['Hora de inicio'].strftime('%H:%M')} a {info['Hora de finalizacion'].strftime('%H:%M')}.")

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
                conflicts.append(f"❌ **Cruce de Estudiantes:** El programa **{row['Programa']}** (Sem. {info['Semestre']}) ya tiene la clase **'{info['Nombre de la clase']}'** ({info['ID']}) programada el **{row['Fecha'].strftime('%Y-%m-%d')}** de {info['Hora de inicio'].strftime('%H:%M')} a {info['Hora de finalizacion'].strftime('%H:%M')}.")
    return conflicts

# --- Funciones Auxiliares ---
def format_for_display(df):
    df_display = df.copy()
    if 'Fecha' in df_display.columns:
        df_display['Fecha'] = pd.to_datetime(df_display['Fecha']).dt.strftime('%Y-%m-%d')
    for col in ['Hora de inicio', 'Hora de finalizacion']:
        if col in df_display.columns:
            df_display[col] = df_display[col].apply(lambda x: x.strftime('%H:%M') if pd.notnull(x) else '')
    return df_display

# --- Inicialización del Estado de la Sesión ---
if 'num_sesiones_a_generar' not in st.session_state:
    st.session_state.num_sesiones_a_generar = 1
if 'modulos_a_generar' not in st.session_state:
    st.session_state.modulos_a_generar = [{'num_sesiones': 1}]

# --- INTERFAZ DE USUARIO (UI) ---
st.title("🗓️ Organizador de Cronogramas de Posgrado")
st.markdown("---")

# --- Formulario para Añadir Clases ---
st.header("➕ Añadir Nueva Clase")

# --- PASO 1: Datos Generales ---
with st.container():
    st.subheader("Paso 1: Datos Generales de la Clase")
    
    # Cargar listas para selectbox
    programas_list = get_unique_values('Programa')
    profesores_list = get_unique_values('Profesor')
    
    col1, col2 = st.columns(2)
    with col1:
        descripcion = st.text_input("Descripción")
        catalogo = st.text_input("# de Catalogo")
        nombre_clase = st.text_input("Nombre de la clase")
        
        # Selectbox para Programa con opción de añadir nuevo
        st.write("Programa")
        add_new_program = st.checkbox("Añadir nuevo programa", key="new_prog_check")
        if add_new_program:
            programa = st.text_input("Nombre del Nuevo Programa", key="new_prog_text")
        else:
            programa = st.selectbox("Selecciona un Programa", options=programas_list, key="prog_select")

    with col2:
        semestre = st.number_input("Semestre", min_value=1, step=1, format="%d")
        creditos = st.number_input("Creditos", min_value=1, step=1, format="%d")
        simultaneo = st.checkbox("¿Permite Simultaneidad?")

# --- PASO 2: Configuración de Horas y Sesiones ---
with st.container():
    st.subheader("Paso 2: Configuración de Horas y Sesiones")
    tipo_clase = st.radio("Tipo de Clase", ["Regular", "Modular"], horizontal=True, key="tipo_clase")
    
    if tipo_clase == "Regular":
        h_col1, h_col2, h_col3 = st.columns([2,2,1])
        horas_totales = h_col1.number_input("Horas totales de la clase", min_value=1.0, step=0.5, format="%.1f")
        horas_por_sesion = h_col2.number_input("Duración de cada sesión (horas)", min_value=0.5, step=0.5, format="%.1f")

        if horas_por_sesion > 0:
            num_sesiones_calculado = math.ceil(horas_totales / horas_por_sesion)
            h_col3.metric("Sesiones a generar", num_sesiones_calculado)
            if h_col3.button("Generar Campos de Sesión"):
                st.session_state.num_sesiones_a_generar = num_sesiones_calculado
    else: # Modular
        num_modulos = st.number_input("Número de Módulos", min_value=1, step=1, format="%d", key="num_modulos_input")
        if st.button("Generar Módulos"):
            st.session_state.modulos_a_generar = [{'num_sesiones': 1} for _ in range(num_modulos)]

# --- PASO 3: Detalles de Sesiones y Envío ---
with st.form("new_class_form"):
    st.subheader("Paso 3: Detalles de Fechas, Horarios y Profesores")
    
    sesiones_data = []

    if st.session_state.tipo_clase == "Regular":
        st.write("Profesor (asignado a todas las sesiones)")
        add_new_prof_reg = st.checkbox("Añadir nuevo profesor", key="new_prof_reg_check")
        if add_new_prof_reg:
            profesor_regular = st.text_input("Nombre del Nuevo Profesor", key="new_prof_reg_text")
        else:
            profesor_regular = st.selectbox("Selecciona un Profesor", options=profesores_list, key="prof_reg_select")
        
        st.markdown("---")
        for i in range(st.session_state.get('num_sesiones_a_generar', 1)):
            st.markdown(f"**Sesión {i+1}**")
            s_col1, s_col2, s_col3 = st.columns(3)
            fecha = s_col1.date_input(f"Fecha", value=date.today(), key=f"reg_date_{i}")
            hora_inicio = s_col2.time_input(f"Inicio", value=time(8, 0), key=f"reg_start_{i}")
            hora_fin = s_col3.time_input(f"Fin", value=time(10, 0), key=f"reg_end_{i}")
            sesiones_data.append({"profesor": profesor_regular, "modulo": 1, "sesion_num": i+1, "fecha": fecha, "hora_inicio": hora_inicio, "hora_fin": hora_fin})

    else: # Modular
        sesion_counter = 1
        for i, mod_config in enumerate(st.session_state.get('modulos_a_generar', [])):
            st.markdown(f"--- \n ### Módulo {i+1}")
            st.write(f"Profesor del Módulo {i+1}")
            add_new_prof_mod = st.checkbox(f"Añadir nuevo profesor para Módulo {i+1}", key=f"new_prof_mod_check_{i}")
            if add_new_prof_mod:
                profesor_modulo = st.text_input(f"Nombre del Nuevo Profesor", key=f"new_prof_mod_text_{i}")
            else:
                profesor_modulo = st.selectbox(f"Selecciona un Profesor", options=profesores_list, key=f"prof_mod_select_{i}")

            num_sesiones_mod = st.number_input(f"Número de sesiones para Módulo {i+1}", min_value=1, step=1, format="%d", value=mod_config['num_sesiones'], key=f"ses_num_mod_{i}")
            # Actualizar el estado si cambia el número de sesiones por módulo (requiere re-generar)
            st.session_state.modulos_a_generar[i]['num_sesiones'] = num_sesiones_mod

            for j in range(num_sesiones_mod):
                st.markdown(f"**Sesión {j+1} del Módulo {i+1}**")
                ms_col1, ms_col2, ms_col3 = st.columns(3)
                fecha = ms_col1.date_input(f"Fecha", value=date.today(), key=f"mod_date_{i}_{j}")
                hora_inicio = ms_col2.time_input(f"Inicio", value=time(8, 0), key=f"mod_start_{i}_{j}")
                hora_fin = ms_col3.time_input(f"Fin", value=time(10, 0), key=f"mod_end_{i}_{j}")
                sesiones_data.append({"profesor": profesor_modulo, "modulo": i+1, "sesion_num": sesion_counter, "fecha": fecha, "hora_inicio": hora_inicio, "hora_fin": hora_fin})
                sesion_counter += 1
    
    submit_button = st.form_submit_button("Añadir Clase al Cronograma")

# --- Lógica de Procesamiento y Validación Final ---
if submit_button:
    # 1. Validaciones básicas
    if not all([descripcion, catalogo, nombre_clase, programa]):
        st.error("Por favor, llena todos los campos de 'Datos Generales' antes de añadir la clase.")
    elif any(s['hora_fin'] <= s['hora_inicio'] for s in sesiones_data):
        st.error("Error: La hora de finalización debe ser posterior a la de inicio para todas las sesiones.")
    else:
        # 2. Construir DataFrame temporal y validar cruces internos
        temp_df = pd.DataFrame(sesiones_data)
        self_conflicts = check_self_overlap(temp_df)
        if self_conflicts:
            st.error("No se pudo añadir la clase. Se encontraron cruces entre las sesiones que intentas registrar:")
            for c in self_conflicts:
                st.warning(c)
        else:
            # 3. Preparar datos para la base de datos y validar contra ella
            records = []
            class_id_base = f"{catalogo}-{nombre_clase.replace(' ', '')[:5]}"
            for s in sesiones_data:
                records.append({
                    'ID': f"{class_id_base}-S{s['sesion_num']}", 'Descripción': descripcion, '# de Catalogo': catalogo, 
                    'Nombre de la clase': nombre_clase, 'Programa': programa, 'Semestre': int(semestre), 'Creditos': int(creditos),
                    'Profesor': s['profesor'], 'Simultaneo': simultaneo, 'Módulo': s['modulo'], 'Sesión': s['sesion_num'], 
                    'Fecha': s['fecha'], 'Hora de inicio': s['hora_inicio'], 'Hora de finalizacion': s['hora_fin']
                })
            final_df = pd.DataFrame(records)
            
            db_conflicts = check_db_conflicts(final_df, st.session_state.schedule_df)
            if db_conflicts:
                st.error("No se pudo añadir la clase. Se encontraron conflictos con el cronograma existente:")
                for c in db_conflicts:
                    st.warning(c)
            else:
                # 4. Insertar en la base de datos si todo está bien
                final_df_insert = final_df.copy()
                final_df_insert['Fecha'] = final_df_insert['Fecha'].astype(str)
                final_df_insert['Hora de inicio'] = final_df_insert['Hora de inicio'].astype(str)
                final_df_insert['Hora de finalizacion'] = final_df_insert['Hora de finalizacion'].astype(str)
                
                try:
                    supabase.table('cronograma').insert(final_df_insert.to_dict('records')).execute()
                    st.success(f"¡Clase '{nombre_clase}' añadida exitosamente!")
                    st.cache_data.clear() # Limpiar cache para recargar datos
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
    filtered_df = st.session_state.schedule_df.copy()
    if programa_filtro:
        filtered_df = filtered_df[filtered_df['Programa'].isin(programa_filtro)]
    if profesor_filtro:
        filtered_df = filtered_df[filtered_df['Profesor'].isin(profesor_filtro)]
    if semestre_filtro:
        filtered_df = filtered_df[filtered_df['Semestre'].isin(semestre_filtro)]
    
    st.dataframe(format_for_display(filtered_df.sort_values(by="Fecha")), use_container_width=True)
    
    csv_completo = st.session_state.schedule_df.to_csv(index=False).encode('utf-8')
    csv_filtrado = filtered_df.to_csv(index=False).encode('utf-8')
    col_desc1, col_desc2 = st.columns(2)
    col_desc1.download_button("📥 Descargar Cronograma Completo (CSV)", csv_completo, 'cronograma_completo.csv', 'text/csv')
    col_desc2.download_button("📥 Descargar Vista Filtrada (CSV)", csv_filtrado, 'cronograma_filtrado.csv', 'text/csv')

    # --- Visualización en Calendario ---
    st.markdown("---")
    st.header("🗓️ Vista de Calendario")
    if not filtered_df.empty:
        calendar_df = filtered_df.copy()
        calendar_df['start'] = calendar_df.apply(lambda row: pd.to_datetime(f"{row['Fecha']} {row['Hora de inicio']}"), axis=1)
        calendar_df['end'] = calendar_df.apply(lambda row: pd.to_datetime(f"{row['Fecha']} {row['Hora de finalizacion']}"), axis=1)
        
        fig = px.timeline(
            calendar_df.sort_values(by="start"), x_start="start", x_end="end", y="Programa",
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

# --- Sección para Eliminar Clases ---
st.markdown("---")
st.header("🗑️ Eliminar Clase del Cronograma")

if not st.session_state.schedule_df.empty:
    with st.form("delete_form"):
        unique_class_ids = st.session_state.schedule_df['ID'].str.split('-S').str[0].unique()
        id_to_delete_base = st.selectbox("Selecciona el ID de la clase a eliminar", options=sorted(unique_class_ids))
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
