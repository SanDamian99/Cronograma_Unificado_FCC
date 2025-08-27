import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import time, date
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

# --- Conexión a Supabase y Carga de Datos ---
@st.cache_resource
def init_connection():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase: Client = init_connection()

@st.cache_data(ttl=60)
def load_data_from_supabase():
    try:
        response = supabase.table('cronograma').select('*').execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['Fecha'] = pd.to_datetime(df['Fecha']).dt.date
            df['Hora de inicio'] = pd.to_datetime(df['Hora de inicio'], format='%H:%M:%S').dt.time
            df['Hora de finalizacion'] = pd.to_datetime(df['Hora de finalizacion'], format='%H:%M:%S').dt.time
        return df
    except Exception as e:
        st.error(f"Error de conexión con Supabase: No se pudo encontrar la tabla 'cronograma'.")
        st.error(f"Detalle del error: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def get_unique_values(column_name):
    # CORRECCIÓN: Se consulta directamente a Supabase para mayor robustez.
    try:
        response = supabase.table('cronograma').select(column_name).execute()
        if response.data:
            return sorted(list(set(item[column_name] for item in response.data if item[column_name] is not None)))
        return []
    except Exception:
        return []


if 'schedule_df' not in st.session_state:
    st.session_state.schedule_df = load_data_from_supabase()

# --- Funciones de Validación ---
def check_self_overlap(df):
    conflicts = []
    for (idx1, row1), (idx2, row2) in itertools.combinations(df.iterrows(), 2):
        if row1['Fecha'] == row2['Fecha']:
            if row1['Hora de inicio'] < row2['Hora de finalizacion'] and row2['Hora de inicio'] < row1['Hora de finalizacion']:
                conflicts.append(f"🔥 **Cruce Interno:** La sesión {idx1 + 1} y la sesión {idx2 + 1} se solapan el mismo día ({row1['Fecha']}).")
    return conflicts

def check_db_conflicts(new_class, existing_df):
    conflicts = []
    if existing_df.empty:
        return conflicts
    for _, row in new_class.iterrows():
        day_schedule = existing_df[existing_df['Fecha'] == row['Fecha']]
        if day_schedule.empty:
            continue
        
        prof_conflict = day_schedule[
            (day_schedule['Profesor'] == row['Profesor']) &
            (day_schedule['Hora de inicio'] < row['Hora de finalizacion']) &
            (day_schedule['Hora de finalizacion'] > row['Hora de inicio'])
        ]
        if not prof_conflict.empty:
            info = prof_conflict.iloc[0]
            conflicts.append(f"❌ **Cruce de Profesor:** El profesor **{row['Profesor']}** ya tiene la clase **'{info['Nombre de la clase']}'** ({info['ID']}) programada el **{row['Fecha'].strftime('%Y-%m-%d')}** de {info['Hora de inicio'].strftime('%H:%M')} a {info['Hora de finalizacion'].strftime('%H:%M')}.")

        if not row['Simultaneo']:
            # BUG CORREGIDO: Se usa la sintaxis correcta de Pandas para el filtro booleano.
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
        if col in df_display.columns and not df_display[col].empty:
            df_display[col] = df_display[col].apply(lambda x: x.strftime('%H:%M') if pd.notnull(x) else '')
    return df_display

def set_add_mode(key, value):
    st.session_state[key] = value

# --- Inicialización del Estado de la Sesión ---
if 'num_sesiones_a_generar' not in st.session_state:
    st.session_state.num_sesiones_a_generar = 1
if 'modulos_a_generar' not in st.session_state:
    st.session_state.modulos_a_generar = [{'num_sesiones': 1}]

# --- INTERFAZ DE USUARIO (UI) ---
st.title("🗓️ Organizador de Cronogramas de Posgrado")

# --- Barra Lateral de Filtros ---
st.sidebar.header("Filtros y Opciones")
programas_list_filter = get_unique_values('Programa')
profesores_list_filter = get_unique_values('Profesor')
semestres_list_filter = get_unique_values('Semestre')

programa_filtro = st.sidebar.multiselect("Filtrar por Programa", options=programas_list_filter)
profesor_filtro = st.sidebar.multiselect("Filtrar por Profesor", options=profesores_list_filter)
semestre_filtro = st.sidebar.multiselect("Filtrar por Semestre", options=semestres_list_filter, format_func=lambda x: f"Semestre {x}")

# --- Formulario para Añadir Clases ---
st.header("➕ Añadir Nueva Clase")

with st.container(border=True):
    st.subheader("Paso 1: Datos Generales")
    col1, col2 = st.columns(2)
    with col1:
        descripcion = st.text_input("Descripción")
        catalogo = st.text_input("# de Catalogo")
        nombre_clase = st.text_input("Nombre de la clase")
        if st.session_state.get('add_new_program_mode', False):
            programa = st.text_input("Nombre del Nuevo Programa", key="new_prog_text")
            if st.button("Cancelar Programa"): set_add_mode('add_new_program_mode', False); st.rerun()
        else:
            programa = st.selectbox("Selecciona un Programa", options=programas_list_filter, key="prog_select")
            if st.button("➕ Añadir Nuevo Programa"): set_add_mode('add_new_program_mode', True); st.rerun()
    with col2:
        semestre = st.number_input("Semestre", min_value=1, step=1, format="%d")
        creditos = st.number_input("Creditos", min_value=1, step=1, format="%d")
        simultaneo = st.checkbox("¿Permite Simultaneidad?")

with st.container(border=True):
    st.subheader("Paso 2: Configuración de Horas y Sesiones")
    tipo_clase = st.radio("Tipo de Clase", ["Regular", "Modular"], horizontal=True, key="tipo_clase")
    if tipo_clase == "Regular":
        h_col1, h_col2, h_col3 = st.columns([2, 2, 1])
        horas_totales = h_col1.number_input("Horas totales", min_value=1.0, step=0.5, format="%.1f")
        horas_por_sesion = h_col2.number_input("Duración por sesión (horas)", min_value=0.5, step=0.5, format="%.1f")
        if horas_por_sesion > 0:
            num_sesiones_calculado = math.ceil(horas_totales / horas_por_sesion)
            h_col3.metric("Sesiones a generar", num_sesiones_calculado)
            if h_col3.button("Generar Campos de Sesión"): st.session_state.num_sesiones_a_generar = num_sesiones_calculado; st.rerun()
    else:
        num_modulos = st.number_input("Número de Módulos", min_value=1, step=1, format="%d", key="num_modulos_input")
        if st.button("Generar Módulos"): st.session_state.modulos_a_generar = [{'num_sesiones': 1} for _ in range(num_modulos)]; st.rerun()

with st.form("new_class_form"):
    st.subheader("Paso 3: Detalles de Fechas, Horarios y Profesores")
    sesiones_data = []
    
    # OPTIMIZACIÓN: Se reutiliza la lista de profesores ya cargada.
    opciones_profesor = ["--- Seleccione un profesor ---"] + profesores_list_filter

    if st.session_state.tipo_clase == "Regular":
        st.markdown("##### Profesor (asignado a todas las sesiones)")
        prof_col1, prof_col2 = st.columns(2)
        profesor_nuevo_reg = prof_col1.text_input("Profesor Nuevo", help="Escribe aquí si el profesor no está en la lista.")
        profesor_existente_reg = prof_col2.selectbox("Profesor Existente", options=opciones_profesor, help="Usa este campo si el profesor ya existe.")
        profesor_regular = profesor_existente_reg if profesor_existente_reg != "--- Seleccione un profesor ---" else profesor_nuevo_reg

        st.markdown("---")
        for i in range(st.session_state.get('num_sesiones_a_generar', 1)):
            st.markdown(f"**Sesión {i + 1}**")
            s_col1, s_col2, s_col3 = st.columns(3)
            fecha = s_col1.date_input("Fecha", value=date.today(), key=f"reg_date_{i}")
            hora_inicio = s_col2.time_input("Inicio", value=time(8, 0), key=f"reg_start_{i}")
            hora_fin = s_col3.time_input("Fin", value=time(10, 0), key=f"reg_end_{i}")
            sesiones_data.append({"Profesor": profesor_regular, "Módulo": 1, "Sesión": i + 1, "Fecha": fecha, "Hora de inicio": hora_inicio, "Hora de finalizacion": hora_fin})
    else:
        sesion_counter = 1
        for i in range(len(st.session_state.get('modulos_a_generar', []))):
            st.markdown(f"--- \n ### Módulo {i + 1}")
            st.markdown(f"##### Profesor del Módulo {i + 1}")
            prof_mod_col1, prof_mod_col2 = st.columns(2)
            profesor_nuevo_mod = prof_mod_col1.text_input(f"Profesor Nuevo (M{i+1})", key=f"prof_nuevo_mod_{i}", help="Escribe aquí si el profesor no está en la lista.")
            profesor_existente_mod = prof_mod_col2.selectbox(f"Profesor Existente (M{i+1})", options=opciones_profesor, key=f"prof_existente_mod_{i}", help="Usa este campo si el profesor ya existe.")
            profesor_modulo = profesor_existente_mod if profesor_existente_mod != "--- Seleccione un profesor ---" else profesor_nuevo_mod

            num_sesiones_mod = st.number_input(f"Sesiones para Módulo {i + 1}", min_value=1, step=1, format="%d", value=st.session_state.modulos_a_generar[i]['num_sesiones'], key=f"ses_num_mod_form_{i}")
            for j in range(num_sesiones_mod):
                st.markdown(f"**Sesión {j + 1} del Módulo {i + 1}**")
                ms_col1, ms_col2, ms_col3 = st.columns(3)
                fecha = ms_col1.date_input("Fecha", value=date.today(), key=f"mod_date_{i}_{j}")
                hora_inicio = ms_col2.time_input("Inicio", value=time(8, 0), key=f"mod_start_{i}_{j}")
                hora_fin = ms_col3.time_input("Fin", value=time(10, 0), key=f"mod_end_{i}_{j}")
                sesiones_data.append({"Profesor": profesor_modulo, "Módulo": i + 1, "Sesión": sesion_counter, "Fecha": fecha, "Hora de inicio": hora_inicio, "Hora de finalizacion": hora_fin})
                sesion_counter += 1
    submit_button = st.form_submit_button("Añadir Clase al Cronograma")

if submit_button:
    if not all([descripcion, catalogo, nombre_clase, programa]):
        st.error("Por favor, llena todos los campos de 'Datos Generales' antes de añadir la clase.")
    elif any(s['Hora de finalizacion'] <= s['Hora de inicio'] for s in sesiones_data):
        st.error("Error: La hora de finalización debe ser posterior a la de inicio para todas las sesiones.")
    elif any(not s['Profesor'] for s in sesiones_data):
        st.error("Error: Todas las sesiones o módulos deben tener un profesor asignado. Por favor, escribe un nombre nuevo o selecciónalo de la lista.")
    else:
        temp_df = pd.DataFrame(sesiones_data)
        self_conflicts = check_self_overlap(temp_df)
        if self_conflicts:
            st.error("No se pudo añadir. Se encontraron cruces entre las sesiones que intentas registrar:")
            for c in self_conflicts: st.warning(c)
        else:
            records = [{'ID': f"{catalogo}-{nombre_clase.replace(' ', '')[:5]}-S{s['Sesión']}", 'Descripción': descripcion, '# de Catalogo': catalogo, 'Nombre de la clase': nombre_clase, 'Programa': programa, 'Semestre': int(semestre), 'Creditos': int(creditos), 'Profesor': s['Profesor'], 'Simultaneo': simultaneo, 'Módulo': s['Módulo'], 'Sesión': s['Sesión'], 'Fecha': s['Fecha'], 'Hora de inicio': s['Hora de inicio'], 'Hora de finalizacion': s['Hora de finalizacion']} for s in sesiones_data]
            final_df = pd.DataFrame(records)
            db_conflicts = check_db_conflicts(final_df, st.session_state.schedule_df)
            if db_conflicts:
                st.error("No se pudo añadir. Se encontraron conflictos con el cronograma existente:")
                for c in db_conflicts: st.warning(c)
            else:
                final_df['Fecha'] = final_df['Fecha'].astype(str)
                final_df['Hora de inicio'] = final_df['Hora de inicio'].astype(str)
                final_df['Hora de finalizacion'] = final_df['Hora de finalizacion'].astype(str)
                try:
                    supabase.table('cronograma').insert(final_df.to_dict('records')).execute()
                    st.success(f"¡Clase '{nombre_clase}' añadida exitosamente!")
                    st.cache_data.clear()
                    st.session_state.schedule_df = load_data_from_supabase()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al guardar en la base de datos: {e}")

# --- Visualización del Cronograma y Eliminación ---
st.markdown("---")
st.header("📅 Cronograma General de Clases")
if st.session_state.schedule_df.empty:
    st.info("Aún no se han añadido clases al cronograma.")
else:
    filtered_df = st.session_state.schedule_df.copy()
    if programa_filtro: filtered_df = filtered_df[filtered_df['Programa'].isin(programa_filtro)]
    if profesor_filtro: filtered_df = filtered_df[filtered_df['Profesor'].isin(profesor_filtro)]
    if semestre_filtro: filtered_df = filtered_df[filtered_df['Semestre'].isin(semestre_filtro)]
    st.dataframe(format_for_display(filtered_df.sort_values(by="Fecha")), width='stretch')
    
    # BUG CORREGIDO: El botón de descarga completa ahora usa el dataframe sin filtrar.
    completo_csv = st.session_state.schedule_df.to_csv(index=False).encode('utf-8')
    filtrado_csv = filtered_df.to_csv(index=False).encode('utf-8')
    col1, col2 = st.columns(2)
    col1.download_button("📥 Descargar Cronograma Completo (CSV)", completo_csv, 'cronograma_completo.csv', 'text/csv')
    col2.download_button("📥 Descargar Vista Filtrada (CSV)", filtrado_csv, 'cronograma_filtrado.csv', 'text/csv')
    
    st.markdown("---")
    st.header("🗓️ Vista de Calendario")
    if not filtered_df.empty:
        filtered_df['start'] = filtered_df.apply(lambda row: pd.to_datetime(f"{row['Fecha']} {row['Hora de inicio']}"), axis=1)
        filtered_df['end'] = filtered_df.apply(lambda row: pd.to_datetime(f"{row['Fecha']} {row['Hora de finalizacion']}"), axis=1)
        fig = px.timeline(filtered_df.sort_values(by="start"), x_start="start", x_end="end", y="Programa", color="Profesor", text="Nombre de la clase", hover_data=['ID', 'Semestre', 'Módulo', 'Fecha'], title="Cronograma de Clases por Programa y Profesor")
        fig.update_layout(xaxis_title="Fecha y Hora", yaxis_title="Programa", plot_bgcolor='#262730', paper_bgcolor='#0E1117', font_color='#FFFFFF', title_font_color='#D4AF37', legend_title_font_color='#D4AF37')
        st.plotly_chart(fig, width='stretch')
    else:
        st.warning("No hay datos para mostrar en el calendario con los filtros actuales.")

    st.markdown("---")
    st.header("🗑️ Eliminar Clase del Cronograma")
    with st.form("delete_form"):
        unique_class_ids = sorted(list(set(st.session_state.schedule_df['ID'].str.split('-S').str[0])))
        id_to_delete_base = st.selectbox("Selecciona el ID de la clase a eliminar", options=unique_class_ids)
        if st.form_submit_button("Eliminar Clase"):
            if id_to_delete_base:
                try:
                    supabase.table('cronograma').delete().like('ID', f'{id_to_delete_base}%').execute()
                    st.success(f"La clase '{id_to_delete_base}' ha sido eliminada.")
                    st.cache_data.clear()
                    st.session_state.schedule_df = load_data_from_supabase()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al eliminar de la base de datos: {e}")
