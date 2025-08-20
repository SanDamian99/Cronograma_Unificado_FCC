import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, time

# --- Configuración de la Página ---
st.set_page_config(
    page_title="Cronograma Posgrados",
    page_icon="🗓️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Estilos CSS para la apariencia ---
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


# --- Inicialización del Estado de la Sesión ---
if 'schedule_df' not in st.session_state:
    st.session_state.schedule_df = pd.DataFrame(columns=[
        'ID', 'Descripción', '# de Catalogo', 'Nombre de la clase', 'Programa', 'Semestre',
        'Creditos', 'Horas', 'Profesor', 'Simultaneo', 'Numero de sesiones',
        'Sesión', 'Día', 'Hora de inicio', 'Hora de finalizacion'
    ])

# --- Funciones Auxiliares ---

def check_conflicts(new_class):
    """Verifica si una nueva clase genera conflictos en el horario existente."""
    df = st.session_state.schedule_df
    conflicts = []

    for index, row in new_class.iterrows():
        # 1. Conflicto para el profesor
        prof_conflict = df[
            (df['Profesor'] == row['Profesor']) &
            (df['Día'] == row['Día']) &
            (df['Hora de inicio'] < row['Hora de finalizacion']) &
            (df['Hora de finalizacion'] > row['Hora de inicio'])
        ]
        if not prof_conflict.empty:
            conflict_info = prof_conflict.iloc[0]
            conflicts.append(
                f"❌ **Cruce de Profesor:** El profesor **{row['Profesor']}** ya tiene la clase "
                f"**{conflict_info['Nombre de la clase']}** ({conflict_info['ID']}) asignada el "
                f"**{row['Día']}** de {conflict_info['Hora de inicio'].strftime('%H:%M')} a "
                f"{conflict_info['Hora de finalizacion'].strftime('%H:%M')}."
            )

        # 2. Conflicto para el programa y semestre (a menos que sea simultánea)
        if not row['Simultaneo']:
            student_conflict = df[
                (df['Programa'] == row['Programa']) &
                (df['Semestre'] == row['Semestre']) &
                (df['Día'] == row['Día']) &
                (df['Hora de inicio'] < row['Hora de finalizacion']) &
                (df['Hora de finalizacion'] > row['Hora de inicio']) &
                (df['Simultaneo'] == False)
            ]
            if not student_conflict.empty:
                conflict_info = student_conflict.iloc[0]
                conflicts.append(
                    f"❌ **Cruce de Estudiantes:** El programa **{row['Programa']}** del semestre **{row['Semestre']}** "
                    f"ya tiene la clase **{conflict_info['Nombre de la clase']}** ({conflict_info['ID']}) programada el "
                    f"**{row['Día']}** de {conflict_info['Hora de inicio'].strftime('%H:%M')} a "
                    f"{conflict_info['Hora de finalizacion'].strftime('%H:%M')}."
                )

    return conflicts

def format_time_for_display(df):
    """Formatea las columnas de tiempo a string HH:MM para una mejor visualización."""
    df_display = df.copy()
    if 'Hora de inicio' in df_display.columns:
        df_display['Hora de inicio'] = df_display['Hora de inicio'].apply(lambda x: x.strftime('%H:%M') if pd.notnull(x) else '')
    if 'Hora de finalizacion' in df_display.columns:
        df_display['Hora de finalizacion'] = df_display['Hora de finalizacion'].apply(lambda x: x.strftime('%H:%M') if pd.notnull(x) else '')
    return df_display


# --- Título y Explicación ---
st.title("🗓️ Organizador de Cronogramas de Posgrado")
st.markdown("---")

with st.expander("ℹ️ ¿Cómo funciona esta aplicación?", expanded=True):
    st.write("""
    Esta herramienta está diseñada para simplificar la creación y gestión de los horarios de clase de los posgrados. Sigue estos pasos:

    1.  **Añadir una Clase:** Utiliza el formulario "Añadir Nueva Clase" para ingresar toda la información de una materia. Puedes elegir entre una clase **Regular** (un solo profesor y horario) o **Modular** (varios módulos, cada uno con su propio profesor y horario).
    2.  **Validación Automática:** Al hacer clic en "Añadir Clase", el sistema revisará automáticamente si la nueva clase genera algún conflicto:
        * **Para el profesor:** Verifica que el profesor no tenga otra clase a la misma hora.
        * **Para los estudiantes:** Asegura que los estudiantes de un mismo programa y semestre no tengan dos clases al mismo tiempo, a menos que una de ellas permita **simultaneidad**.
    3.  **Gestión del Cronograma:**
        * La tabla "Cronograma General de Clases" mostrará todas las materias añadidas.
        * Usa los **filtros** en la barra lateral para buscar por programa, profesor o semestre.
        * Visualiza el horario de forma gráfica en el **calendario semanal**.
    4.  **Exportar y Eliminar:**
        * Puedes **descargar** la tabla completa o la vista filtrada en formato CSV.
        * Si necesitas eliminar una clase, simplemente introduce su **ID** en la sección de eliminación.

    ¡El objetivo es unificar y hacer más eficiente todo el proceso de programación académica!
    """)
st.markdown("---")


# --- Barra Lateral: Filtros y Opciones ---
st.sidebar.header("Filtros y Opciones")

# Obtener opciones únicas para los filtros
programas = st.session_state.schedule_df['Programa'].unique()
profesores = st.session_state.schedule_df['Profesor'].unique()
semestres = st.session_state.schedule_df['Semestre'].unique()

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
        semestre = st.number_input("Semestre", min_value=1, step=1)
        creditos = st.number_input("Creditos", min_value=1, step=1)

    with col2:
        horas = st.number_input("Horas totales", min_value=1, step=1)
        simultaneo = st.checkbox("¿Permite Simultaneidad?")
        num_sesiones = st.number_input("Número de sesiones/módulos", min_value=1, step=1)

    st.markdown("---")
    st.subheader("Detalles de las Sesiones")
    
    sesiones_data = []
    
    if tipo_clase == "Regular":
        st.write("**Clase Regular:** Todas las sesiones tienen el mismo profesor y horario.")
        profesor = st.text_input("Profesor Asignado")
        dia = st.selectbox("Día de la semana", ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"])
        hora_inicio = st.time_input("Hora de Inicio")
        hora_fin = st.time_input("Hora de Finalización")

        for i in range(num_sesiones):
            sesiones_data.append({
                "profesor": profesor,
                "dia": dia,
                "hora_inicio": hora_inicio,
                "hora_fin": hora_fin
            })
            
    else: # Modular
        st.write("**Clase Modular:** Define un profesor y horario para cada módulo.")
        for i in range(num_sesiones):
            st.markdown(f"**Módulo {i+1}**")
            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            with m_col1:
                profesor = st.text_input(f"Profesor Módulo {i+1}", key=f"prof_{i}")
            with m_col2:
                dia = st.selectbox(f"Día Módulo {i+1}", ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"], key=f"dia_{i}")
            with m_col3:
                hora_inicio = st.time_input(f"Inicio Módulo {i+1}", key=f"start_{i}")
            with m_col4:
                hora_fin = st.time_input(f"Fin Módulo {i+1}", key=f"end_{i}")

            sesiones_data.append({
                "profesor": profesor,
                "dia": dia,
                "hora_inicio": hora_inicio,
                "hora_fin": hora_fin
            })

    submit_button = st.form_submit_button("Añadir Clase al Cronograma")


if submit_button:
    if hora_fin <= hora_inicio:
        st.error("La hora de finalización debe ser posterior a la hora de inicio.")
    else:
        # Crear un DataFrame temporal con la nueva clase
        new_class_records = []
        # Generar un ID único para la clase basado en el catálogo y el nombre
        class_id = f"{catalogo}-{nombre_clase.replace(' ', '')[:5]}"
        
        for i, sesion in enumerate(sesiones_data):
            new_class_records.append({
                'ID': f"{class_id}-S{i+1}",
                'Descripción': descripcion,
                '# de Catalogo': catalogo,
                'Nombre de la clase': nombre_clase,
                'Programa': programa,
                'Semestre': semestre,
                'Creditos': creditos,
                'Horas': horas,
                'Profesor': sesion['profesor'],
                'Simultaneo': simultaneo,
                'Numero de sesiones': num_sesiones,
                'Sesión': i + 1,
                'Día': sesion['dia'],
                'Hora de inicio': sesion['hora_inicio'],
                'Hora de finalizacion': sesion['hora_fin']
            })
        
        temp_df = pd.DataFrame(new_class_records)
        temp_df['Hora de inicio'] = pd.to_datetime(temp_df['Hora de inicio'].astype(str), format='%H:%M:%S').dt.time
        temp_df['Hora de finalizacion'] = pd.to_datetime(temp_df['Hora de finalizacion'].astype(str), format='%H:%M:%S').dt.time
        
        # Verificar conflictos
        conflictos = check_conflicts(temp_df)

        if conflictos:
            st.error("No se pudo añadir la clase debido a los siguientes conflictos:")
            for conflicto in conflictos:
                st.warning(conflicto)
        else:
            # Si no hay conflictos, añadir al DataFrame principal
            st.session_state.schedule_df = pd.concat([st.session_state.schedule_df, temp_df], ignore_index=True)
            st.success(f"¡Clase '{nombre_clase}' añadida exitosamente al cronograma!")


# --- Visualización del Cronograma ---
st.markdown("---")
st.header("📅 Cronograma General de Clases")

if st.session_state.schedule_df.empty:
    st.info("Aún no se han añadido clases al cronograma.")
else:
    # Mostrar la tabla filtrada
    st.dataframe(format_time_for_display(filtered_df), use_container_width=True)

    # Botón de descarga
    csv_completo = st.session_state.schedule_df.to_csv(index=False).encode('utf-8')
    csv_filtrado = filtered_df.to_csv(index=False).encode('utf-8')

    col_desc1, col_desc2 = st.columns(2)
    with col_desc1:
        st.download_button(
            label="📥 Descargar Cronograma Completo (CSV)",
            data=csv_completo,
            file_name='cronograma_completo.csv',
            mime='text/csv',
        )
    with col_desc2:
        st.download_button(
            label="📥 Descargar Vista Filtrada (CSV)",
            data=csv_filtrado,
            file_name='cronograma_filtrado.csv',
            mime='text/csv',
        )

    # --- Visualización en Calendario ---
    st.markdown("---")
    st.header("🗓️ Vista de Calendario Semanal")
    
    if not filtered_df.empty:
        # Mapeo de días a números para el orden correcto
        day_map = {"Lunes": 1, "Martes": 2, "Miércoles": 3, "Jueves": 4, "Viernes": 5, "Sábado": 6, "Domingo": 7}
        calendar_df = filtered_df.copy()
        calendar_df['day_num'] = calendar_df['Día'].map(day_map)
        calendar_df = calendar_df.sort_values(by=['day_num', 'Hora de inicio'])

        # Creación de la figura del calendario con Plotly
        fig = px.timeline(
            calendar_df,
            x_start="Hora de inicio",
            x_end="Hora de finalizacion",
            y="Profesor",
            color="Programa",
            text="Nombre de la clase",
            hover_data=['ID', 'Semestre', 'Día'],
            title="Distribución de Clases por Profesor y Programa",
            facet_row="Día" # Separa los días en filas distintas
        )

        fig.update_layout(
            xaxis_title="Hora del Día",
            yaxis_title="Profesor",
            plot_bgcolor='#262730',
            paper_bgcolor='#0E1117',
            font_color='#FFFFFF',
            title_font_color='#D4AF37',
            legend_title_font_color='#D4AF37'
        )
        fig.update_yaxes(autorange="reversed") # Invierte el eje y para mejor lectura
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No hay datos para mostrar en el calendario con los filtros actuales.")


# --- Sección para Eliminar Clases ---
st.markdown("---")
st.header("🗑️ Eliminar Clase del Cronograma")

if not st.session_state.schedule_df.empty:
    with st.form("delete_form"):
        # Obtener IDs únicos de las clases (base) para la selección
        unique_class_ids = st.session_state.schedule_df['ID'].str.split('-S').str[0].unique()
        id_to_delete_base = st.selectbox("Selecciona el ID de la clase a eliminar", options=unique_class_ids)
        
        delete_button = st.form_submit_button("Eliminar Clase")

        if delete_button and id_to_delete_base:
            # Eliminar todas las sesiones/módulos asociados con ese ID base
            initial_rows = len(st.session_state.schedule_df)
            st.session_state.schedule_df = st.session_state.schedule_df[
                ~st.session_state.schedule_df['ID'].str.startswith(id_to_delete_base)
            ]
            if len(st.session_state.schedule_df) < initial_rows:
                st.success(f"La clase con ID base '{id_to_delete_base}' y todas sus sesiones han sido eliminadas.")
                st.experimental_rerun()
            else:
                st.error("No se encontró ninguna clase con ese ID.")
else:
    st.info("El cronograma está vacío, no hay clases para eliminar.")
