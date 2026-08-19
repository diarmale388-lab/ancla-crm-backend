import re
import json
import logging
from datetime import datetime
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.models.base import Contact, Appointment, User
from app.core.deps import get_current_user

logger = logging.getLogger("showroom_router")
router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard de Lanzamiento Showroom ANCLA</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0e14;
            --panel-bg: #151b26;
            --panel-border: #262f40;
            --text-color: #c9d1d9;
            --text-muted: #7d8590;
            --accent-green: #2ea043;
            --accent-purple: #9b51e0;
            --accent-blue: #2f80ed;
            --accent-orange: #f2994a;
            --card-hover: #1e2638;
            --modal-bg: rgba(21, 27, 38, 0.95);
        }
        
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Outfit', sans-serif;
        }
        
        body {
            background-color: var(--bg-color);
            color: var(--text-color);
            padding: 20px;
            min-height: 100vh;
        }
        
        header {
            margin-bottom: 25px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--panel-border);
            padding-bottom: 16px;
        }
        
        .logo-title h1 {
            font-size: 24px;
            font-weight: 700;
            color: #ffffff;
            letter-spacing: -0.5px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .logo-title h1 span {
            color: var(--accent-purple);
            text-shadow: 0 0 10px rgba(155, 81, 224, 0.3);
        }
        
        .logo-title p {
            color: var(--text-muted);
            margin-top: 4px;
            font-size: 13px;
        }
        
        /* Estadísticas */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 25px;
        }
        
        .stat-card {
            background: var(--panel-bg);
            border: 1px solid var(--panel-border);
            padding: 16px;
            border-radius: 12px;
            display: flex;
            flex-direction: column;
            position: relative;
            overflow: hidden;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.2);
        }
        
        .stat-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
        }
        
        .stat-card.total::before { background-color: var(--accent-blue); }
        .stat-card.presencial::before { background-color: var(--accent-green); }
        .stat-card.virtual::before { background-color: var(--accent-purple); }
        .stat-card.lote::before { background-color: var(--accent-orange); }
        
        .stat-card h3 {
            font-size: 11px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.8px;
        }
        
        .stat-card .value {
            font-size: 28px;
            font-weight: 700;
            color: #ffffff;
            margin-top: 8px;
            display: flex;
            align-items: baseline;
            gap: 4px;
        }
        
        .stat-card .unit {
            font-size: 12px;
            font-weight: 400;
            color: var(--text-muted);
        }
        
        /* Controles de Filtrado */
        .filter-panel {
            background: var(--panel-bg);
            border: 1px solid var(--panel-border);
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 25px;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.2);
        }
        
        .filter-title {
            font-size: 15px;
            font-weight: 600;
            color: #ffffff;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .filter-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
        }
        
        .filter-group {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        
        .filter-group label {
            font-size: 11px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .filter-group select, .filter-group input {
            background: var(--bg-color);
            border: 1px solid var(--panel-border);
            color: var(--text-color);
            padding: 8px 12px;
            border-radius: 8px;
            outline: none;
            font-size: 13px;
        }
        
        /* Listado de Asistentes */
        .list-container {
            background: var(--panel-bg);
            border: 1px solid var(--panel-border);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.2);
        }
        
        .list-header {
            padding: 16px 20px;
            border-bottom: 1px solid var(--panel-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .list-header h2 {
            font-size: 16px;
            font-weight: 600;
            color: #ffffff;
        }
        
        .list-header .count-badge {
            background: rgba(47, 128, 237, 0.1);
            border: 1px solid rgba(47, 128, 237, 0.2);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
            color: #79c0ff;
        }
        
        /* Tabla Premium */
        .table-wrapper {
            overflow-x: auto;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }
        
        th {
            background: rgba(0, 0, 0, 0.15);
            padding: 12px 20px;
            font-size: 11px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            border-bottom: 1px solid var(--panel-border);
        }
        
        td {
            padding: 14px 20px;
            border-bottom: 1px solid var(--panel-border);
            font-size: 13px;
            vertical-align: middle;
        }
        
        tr:hover td {
            background-color: var(--card-hover);
        }
        
        .client-info {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        
        .client-name {
            font-weight: 600;
            color: #ffffff;
            font-size: 14px;
        }
        
        .client-id {
            font-size: 11px;
            color: var(--text-muted);
        }
        
        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
        }
        
        .badge.presencial {
            background: rgba(46, 160, 67, 0.12);
            color: #56d364;
            border: 1px solid rgba(46, 160, 67, 0.2);
        }
        
        .badge.virtual {
            background: rgba(155, 81, 224, 0.12);
            color: #d3b6ff;
            border: 1px solid rgba(155, 81, 224, 0.2);
        }
        
        .badge.natural {
            background: rgba(47, 128, 237, 0.08);
            color: #79c0ff;
            border: 1px solid rgba(47, 128, 237, 0.15);
        }
        
        .badge.empresa {
            background: rgba(242, 153, 74, 0.08);
            color: #f7a261;
            border: 1px solid rgba(242, 153, 74, 0.15);
        }
        
        .badge.origin-meta {
            background: rgba(88, 166, 255, 0.1);
            color: #58a6ff;
            border: 1px solid rgba(88, 166, 255, 0.2);
        }
        
        .badge.origin-direct {
            background: rgba(139, 148, 158, 0.1);
            color: var(--text-color);
            border: 1px solid rgba(139, 148, 158, 0.15);
        }
        
        .badge.lote-si {
            background: rgba(47, 128, 237, 0.12);
            color: #58a6ff;
        }
        
        .badge.lote-no {
            background: rgba(248, 81, 73, 0.1);
            color: #ff7b72;
        }
        
        .badge.day-mar {
            background: #1c212c;
            color: #ffffff;
            border: 1px solid var(--panel-border);
        }
        
        .badge.day-mie {
            background: #271c3b;
            color: #d3b6ff;
            border: 1px solid rgba(155, 81, 224, 0.2);
        }
        
        .time-text {
            font-weight: 600;
            color: #ffffff;
            margin-top: 2px;
        }
        
        .btn {
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            text-decoration: none;
            cursor: pointer;
            outline: none;
            border: none;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s;
        }
        
        .btn-view {
            background: rgba(88, 166, 255, 0.1);
            color: #58a6ff;
            border: 1px solid rgba(88, 166, 255, 0.2);
        }
        
        .btn-view:hover {
            background: rgba(88, 166, 255, 0.2);
            transform: translateY(-1px);
        }
        
        .btn-pdf {
            background: #e74c3c;
            color: #ffffff;
            box-shadow: 0 4px 10px rgba(231, 76, 60, 0.2);
        }
        
        .btn-pdf:hover {
            background: #c0392b;
            transform: translateY(-1px);
            box-shadow: 0 6px 15px rgba(231, 76, 60, 0.3);
        }
        
        .whatsapp-btn {
            background: #25d366;
            color: #000000;
            box-shadow: 0 4px 10px rgba(37, 211, 102, 0.15);
        }
        
        .whatsapp-btn:hover {
            background: #20ba5a;
            transform: translateY(-1px);
            box-shadow: 0 6px 15px rgba(37, 211, 102, 0.25);
        }
        
        .no-results {
            padding: 30px;
            text-align: center;
            color: var(--text-muted);
            font-size: 14px;
        }
        
        /* Estilos del Modal */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(5px);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 1000;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease;
        }
        
        .modal-overlay.active {
            opacity: 1;
            pointer-events: auto;
        }
        
        .modal-content {
            background: var(--panel-bg);
            border: 1px solid var(--panel-border);
            width: 95%;
            max-width: 500px;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
            transform: scale(0.9);
            transition: transform 0.3s ease;
        }
        
        .modal-overlay.active .modal-content {
            transform: scale(1);
        }
        
        .modal-header {
            padding: 16px 20px;
            border-bottom: 1px solid var(--panel-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(0, 0, 0, 0.1);
        }
        
        .modal-header h3 {
            font-size: 16px;
            font-weight: 700;
            color: #ffffff;
        }
        
        .modal-close {
            background: none;
            border: none;
            color: var(--text-muted);
            font-size: 20px;
            cursor: pointer;
        }
        
        .modal-close:hover {
            color: #ffffff;
        }
        
        .modal-body {
            padding: 20px;
            max-height: 65vh;
            overflow-y: auto;
        }
        
        .tech-sheet {
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        
        .sheet-section {
            border-bottom: 1px solid var(--panel-border);
            padding-bottom: 12px;
        }
        
        .sheet-section:last-child {
            border-bottom: none;
            padding-bottom: 0;
        }
        
        .sheet-section-title {
            font-size: 11px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        
        .sheet-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
        }
        
        .sheet-item {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        
        .sheet-label {
            font-size: 11px;
            color: var(--text-muted);
        }
        
        .sheet-value {
            font-size: 13px;
            font-weight: 600;
            color: #ffffff;
        }
        
        .notes-box {
            background: var(--bg-color);
            border: 1px solid var(--panel-border);
            padding: 12px;
            border-radius: 8px;
            font-size: 12px;
            line-height: 1.5;
            color: var(--text-color);
            white-space: pre-line;
        }
        
        .modal-footer {
            padding: 12px 20px;
            border-top: 1px solid var(--panel-border);
            display: flex;
            justify-content: flex-end;
            background: rgba(0, 0, 0, 0.1);
        }

        /* 📱 RESPONSIVIDAD EXTREMA PARA CELULARES (TRANSFORMACIÓN DE TABLA EN TARJETAS) */
        @media (max-width: 768px) {
            body {
                padding: 12px;
            }
            
            header {
                flex-direction: column;
                align-items: flex-start;
                gap: 10px;
            }
            
            .table-wrapper {
                overflow-x: visible;
            }
            
            table, thead, tbody, th, td, tr {
                display: block;
            }
            
            thead tr {
                position: absolute;
                top: -9999px;
                left: -9999px;
            }
            
            tr {
                border: 1px solid var(--panel-border);
                border-radius: 12px;
                margin-bottom: 16px;
                padding: 16px;
                background: rgba(255, 255, 255, 0.01);
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.15);
            }
            
            td {
                border: none;
                padding: 10px 0;
                position: relative;
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            }
            
            td:last-child {
                border-bottom: none;
                padding-bottom: 0;
            }
            
            /* Insertar etiqueta de columna responsiva */
            td::before {
                content: attr(data-label);
                font-weight: 700;
                color: var(--text-muted);
                font-size: 11px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                display: inline-block;
                width: 45%;
                text-align: left;
            }
            
            td > * {
                width: 55%;
                text-align: right;
                display: flex;
                justify-content: flex-end;
            }
            
            .client-info {
                align-items: flex-end;
            }
            
            .btn-view {
                align-self: flex-end !important;
            }
        }

        /* 🖨️ ESTILOS DE IMPRESIÓN (PDF LIMPIO) */
        @media print {
            body {
                background: white !important;
                color: black !important;
                padding: 0 !important;
            }
            
            .filter-panel, .stats-grid, header, .btn, .count-badge, .modal-overlay {
                display: none !important;
            }
            
            .list-container {
                border: none !important;
                background: white !important;
                box-shadow: none !important;
            }
            
            .list-header {
                border-bottom: 2px solid black !important;
                padding: 10px 0 !important;
            }
            
            .list-header h2 {
                color: black !important;
                font-size: 20px !important;
            }
            
            table {
                width: 100% !important;
                border-collapse: collapse !important;
            }
            
            th {
                background: #f2f2f2 !important;
                color: black !important;
                border-bottom: 2px solid black !important;
                font-size: 11px !important;
            }
            
            td {
                color: black !important;
                border-bottom: 1px solid #ccc !important;
                font-size: 11px !important;
            }
            
            .badge {
                border: 1px solid black !important;
                background: transparent !important;
                color: black !important;
            }
            
            .time-text, .client-name {
                color: black !important;
            }
            
            .client-id {
                color: #555 !important;
            }
        }
        
    </style>
</head>
<body>

    <header>
        <div class="logo-title">
            <h1>🏠 ANCLA Special Projects <span>Showroom</span></h1>
            <p>Listado Interactivo y Fichas de Clientes Confirmados (28 y 29 de Julio)</p>
        </div>
    </header>

    <div class="stats-grid">
        <div class="stat-card total">
            <h3>Total Filtrados</h3>
            <div class="value" id="stat-total">0 <span class="unit">contactos</span></div>
        </div>
        <div class="stat-card presencial">
            <h3>Presenciales Showroom</h3>
            <div class="value" id="stat-presencial">0 <span class="unit">visitas</span></div>
        </div>
        <div class="stat-card virtual">
            <h3>Asesorías Virtuales</h3>
            <div class="value" id="stat-virtual">0 <span class="unit">llamadas</span></div>
        </div>
        <div class="stat-card lote">
            <h3>Clientes con Lote</h3>
            <div class="value" id="stat-lote">0 <span class="unit">terrenos</span></div>
        </div>
    </div>

    <div class="filter-panel">
        <div class="filter-title">
            <span>🔍 Filtros y Búsqueda Dinámica</span>
            <button class="btn btn-pdf" onclick="window.print()">📥 Descargar Reporte PDF</button>
        </div>
        <div class="filter-grid">
            <div class="filter-group">
                <label for="search-input">Buscador Cliente</label>
                <input type="text" id="search-input" placeholder="Nombre, teléfono, ciudad, notas...">
            </div>
            <div class="filter-group">
                <label for="filter-day">Día</label>
                <select id="filter-day">
                    <option value="all">Todos los días</option>
                    <option value="Martes 28 de Julio">Martes 28 de Julio</option>
                    <option value="Miércoles 29 de Julio">Miércoles 29 de Julio</option>
                </select>
            </div>
            <div class="filter-group">
                <label for="filter-modality">Modalidad</label>
                <select id="filter-modality">
                    <option value="all">Todas las modalidades</option>
                    <option value="Presencial (Showroom Armenia)">Presencial (Showroom)</option>
                    <option value="Virtual (Llamada/Meet)">Virtual (Llamada/Meet)</option>
                </select>
            </div>
            <div class="filter-group">
                <label for="filter-origin">Origen de Campaña</label>
                <select id="filter-origin">
                    <option value="all">Todos los orígenes</option>
                    <option value="Campaña Formulario (Meta)">Campaña Formulario (Meta Ads)</option>
                    <option value="Campaña Directa / Orgánico">Campaña Directa / Orgánico</option>
                </select>
            </div>
            <div class="filter-group">
                <label for="filter-type">Perfil Cliente</label>
                <select id="filter-type">
                    <option value="all">Todos los perfiles</option>
                    <option value="Persona Natural">Persona Natural</option>
                    <option value="Empresa / Inversionista">Empresario / Inversionista</option>
                </select>
            </div>
            <div class="filter-group">
                <label for="filter-hour">Jornada</label>
                <select id="filter-hour">
                    <option value="all">Todas las horas</option>
                    <option value="mañana">Mañana (Antes 12 PM)</option>
                    <option value="tarde">Tarde (12 PM en adelante)</option>
                </select>
            </div>
        </div>
    </div>

    <div class="list-container">
        <div class="list-header">
            <h2>Asistentes al Evento</h2>
            <div class="count-badge" id="results-count">0 registros encontrados</div>
        </div>
        
        <div class="table-wrapper">
            <table id="attendees-table">
                <thead>
                    <tr>
                        <th>Cliente</th>
                        <th>Día / Hora</th>
                        <th>Modalidad</th>
                        <th>Campaña Origen</th>
                        <th>Perfil</th>
                        <th>Lote</th>
                        <th>Propósito / Ciudad</th>
                        <th>Ficha Calificación</th>
                    </tr>
                </thead>
                <tbody id="table-body">
                    <!-- Filas dinámicas -->
                </tbody>
            </table>
        </div>
        <div id="no-results" class="no-results" style="display: none;">
            No se encontraron clientes confirmados con los filtros seleccionados.
        </div>
    </div>

    <!-- MODAL DE FICHA TÉCNICA -->
    <div class="modal-overlay" id="sheet-modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3 id="modal-client-name">Ficha Técnica de Cliente</h3>
                <button class="modal-close" id="modal-close-btn">&times;</button>
            </div>
            <div class="modal-body">
                <div class="tech-sheet">
                    <div class="sheet-section">
                        <div class="sheet-section-title">👤 Información Básica</div>
                        <div class="sheet-grid">
                            <div class="sheet-item">
                                <span class="sheet-label">Nombre Completo</span>
                                <span class="sheet-value" id="sheet-name">-</span>
                            </div>
                            <div class="sheet-item">
                                <span class="sheet-label">Teléfono WhatsApp</span>
                                <span class="sheet-value" id="sheet-phone">-</span>
                            </div>
                            <div class="sheet-item">
                                <span class="sheet-label">Correo Electrónico</span>
                                <span class="sheet-value" id="sheet-email">-</span>
                            </div>
                            <div class="sheet-item">
                                <span class="sheet-label">Ciudad / Procedencia</span>
                                <span class="sheet-value" id="sheet-city">-</span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="sheet-section">
                        <div class="sheet-section-title">🗓️ Detalles de Reserva</div>
                        <div class="sheet-grid">
                            <div class="sheet-item">
                                <span class="sheet-label">Día de Visita</span>
                                <span class="sheet-value" id="sheet-day">-</span>
                            </div>
                            <div class="sheet-item">
                                <span class="sheet-label">Hora Agendada</span>
                                <span class="sheet-value" id="sheet-time">-</span>
                            </div>
                            <div class="sheet-item">
                                <span class="sheet-label">Modalidad Cita</span>
                                <span class="sheet-value" id="sheet-modality">-</span>
                            </div>
                            <div class="sheet-item">
                                <span class="sheet-label">Origen Tráfico</span>
                                <span class="sheet-value" id="sheet-origin">-</span>
                            </div>
                        </div>
                    </div>

                    <div class="sheet-section">
                        <div class="sheet-section-title">📊 Perfil Comercial de Proyecto</div>
                        <div class="sheet-grid">
                            <div class="sheet-item">
                                <span class="sheet-label">Tipo de Lote</span>
                                <span class="sheet-value" id="sheet-lote">-</span>
                            </div>
                            <div class="sheet-item">
                                <span class="sheet-label">Propósito Comercial</span>
                                <span class="sheet-value" id="sheet-purpose">-</span>
                            </div>
                            <div class="sheet-item">
                                <span class="sheet-label">Perfil de Cliente</span>
                                <span class="sheet-value" id="sheet-type">-</span>
                            </div>
                        </div>
                    </div>

                    <div class="sheet-section">
                        <div class="sheet-section-title">📝 Notas Completas / Respuestas del Formulario</div>
                        <div class="notes-box" id="sheet-notes">
                            -
                        </div>
                    </div>
                </div>
            </div>
            <div class="modal-footer">
                <a href="#" target="_blank" class="btn whatsapp-btn" id="modal-wa-btn">
                    <span>💬</span> Abrir Chat en WhatsApp
                </a>
            </div>
        </div>
    </div>

    <script>
        const attendees = {json_str};

        const searchInput = document.getElementById('search-input');
        const filterDay = document.getElementById('filter-day');
        const filterModality = document.getElementById('filter-modality');
        const filterOrigin = document.getElementById('filter-origin');
        const filterType = document.getElementById('filter-type');
        const filterHour = document.getElementById('filter-hour');
        const tableBody = document.getElementById('table-body');
        const noResults = document.getElementById('no-results');
        const resultsCount = document.getElementById('results-count');
        
        const statTotal = document.getElementById('stat-total');
        const statPresencial = document.getElementById('stat-presencial');
        const statVirtual = document.getElementById('stat-virtual');
        const statLote = document.getElementById('stat-lote');

        const modal = document.getElementById('sheet-modal');
        const modalCloseBtn = document.getElementById('modal-close-btn');
        const sheetName = document.getElementById('sheet-name');
        const sheetPhone = document.getElementById('sheet-phone');
        const sheetEmail = document.getElementById('sheet-email');
        const sheetCity = document.getElementById('sheet-city');
        const sheetDay = document.getElementById('sheet-day');
        const sheetTime = document.getElementById('sheet-time');
        const sheetModality = document.getElementById('sheet-modality');
        const sheetOrigin = document.getElementById('sheet-origin');
        const sheetLote = document.getElementById('sheet-lote');
        const sheetPurpose = document.getElementById('sheet-purpose');
        const sheetType = document.getElementById('sheet-type');
        const sheetNotes = document.getElementById('sheet-notes');
        const modalWaBtn = document.getElementById('modal-wa-btn');

        function updateStats(items) {
            statTotal.innerHTML = items.length + ' <span class="unit">contactos</span>';
            statPresencial.innerHTML = items.filter(x => x.modality.includes('Presencial')).length + ' <span class="unit">visitas</span>';
            statVirtual.innerHTML = items.filter(x => x.modality.includes('Virtual')).length + ' <span class="unit">llamadas</span>';
            statLote.innerHTML = items.filter(x => x.has_lote.includes('Sí')).length + ' <span class="unit">terrenos</span>';
        }

        window.openSheet = function(contactId) {
            const item = attendees.find(x => x.contact_id === contactId);
            if (!item) return;

            sheetName.textContent = item.name;
            sheetPhone.textContent = '+' + item.phone;
            sheetEmail.textContent = item.email;
            sheetCity.textContent = item.city;
            sheetDay.textContent = item.day;
            sheetTime.textContent = item.time;
            sheetModality.textContent = item.modality;
            sheetOrigin.textContent = item.origin;
            sheetLote.textContent = item.has_lote;
            sheetPurpose.textContent = item.purpose;
            sheetType.textContent = item.client_type;
            sheetNotes.textContent = item.notes;
            
            const cleanPhone = item.phone.replace(/[^0-9]/g, '');
            modalWaBtn.href = 'https://wa.me/' + cleanPhone;

            modal.classList.add('active');
        }

        modalCloseBtn.addEventListener('click', () => {
            modal.classList.remove('active');
        });
        
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.remove('active');
            }
        });

        function renderTable(items) {
            tableBody.innerHTML = '';
            
            if (items.length === 0) {
                noResults.style.display = 'block';
                resultsCount.textContent = '0 registros encontrados';
                return;
            }
            
            noResults.style.display = 'none';
            resultsCount.textContent = items.length + ' registros encontrados';
            
            items.forEach(item => {
                const tr = document.createElement('tr');
                
                const badgeModality = item.modality.includes('Presencial') 
                    ? '<span class="badge presencial">Presencial</span>'
                    : '<span class="badge virtual">Virtual</span>';
                    
                const badgeType = item.client_type.includes('Empresa')
                    ? '<span class="badge empresa">Empresario</span>'
                    : '<span class="badge natural">Natural</span>';
                    
                const badgeOrigin = item.origin.includes('Meta')
                    ? '<span class="badge origin-meta">Form Meta Ads</span>'
                    : '<span class="badge origin-direct">Directa / Orgánico</span>';
                    
                const badgeLote = item.has_lote.includes('Sí')
                    ? '<span class="badge lote-si">Sí, Lote</span>'
                    : '<span class="badge lote-no">Buscando</span>';
                    
                const badgeDay = item.day.includes('Martes')
                    ? '<span class="badge day-mar">Martes 28</span>'
                    : '<span class="badge day-mie">Miércoles 29</span>';
                
                let shortNotes = item.notes.replace(/\\[Meta Ads Atribución\\]:.*\\n?/, '').trim();
                if (shortNotes.length > 80) {
                    shortNotes = shortNotes.substring(0, 80) + '...';
                }
                
                tr.innerHTML = `
                    <td data-label="Cliente">
                        <div class="client-info">
                            <span class="client-name">${item.name}</span>
                            <span class="client-id">ID #${item.contact_id} | ${item.phone}</span>
                        </div>
                    </td>
                    <td data-label="Día / Hora">
                        <div style="display: flex; flex-direction: column; gap: 4px;">
                            ${badgeDay}
                            <span class="time-text">${item.time}</span>
                        </div>
                    </td>
                    <td data-label="Modalidad">${badgeModality}</td>
                    <td data-label="Campaña Origen">${badgeOrigin}</td>
                    <td data-label="Perfil">${badgeType}</td>
                    <td data-label="Lote">${badgeLote}</td>
                    <td data-label="Propósito / Ciudad">
                        <div style="display: flex; flex-direction: column; gap: 4px;">
                            <span style="font-weight: 600; color: #ffffff;">${item.city}</span>
                            <span style="font-size: 11px; color: var(--text-muted);">${item.purpose}</span>
                        </div>
                    </td>
                    <td data-label="Ficha Calificación">
                        <div style="display: flex; flex-direction: column; gap: 6px;">
                            <span style="font-size: 12px; color: var(--text-muted);">${shortNotes}</span>
                            <button class="btn btn-view" style="padding: 4px 8px; font-size: 11px; align-self: flex-start;" onclick="openSheet(${item.contact_id})">📄 Ver Ficha Completa</button>
                        </div>
                    </td>
                `;
                
                tableBody.appendChild(tr);
            });
        }

        function filterAttendees() {
            const searchVal = searchInput.value.toLowerCase().trim();
            const dayVal = filterDay.value;
            const modalityVal = filterModality.value;
            const originVal = filterOrigin.value;
            const typeVal = filterType.value;
            const hourVal = filterHour.value;
            
            const filtered = attendees.filter(item => {
                const matchesSearch = !searchVal || 
                    item.name.toLowerCase().includes(searchVal) ||
                    item.phone.includes(searchVal) ||
                    item.city.toLowerCase().includes(searchVal) ||
                    item.notes.toLowerCase().includes(searchVal);
                    
                const matchesDay = dayVal === 'all' || item.day === dayVal;
                const matchesModality = modalityVal === 'all' || item.modality === modalityVal;
                const matchesOrigin = originVal === 'all' || item.origin === originVal;
                const matchesType = typeVal === 'all' || item.client_type === typeVal;
                
                let matchesHour = true;
                if (hourVal === 'mañana') {
                    matchesHour = item.hour_num < 12;
                } else if (hourVal === 'tarde') {
                    matchesHour = item.hour_num >= 12;
                }
                
                return matchesSearch && matchesDay && matchesModality && matchesOrigin && matchesType && matchesHour;
            });
            
            updateStats(filtered);
            renderTable(filtered);
        }

        searchInput.addEventListener('input', filterAttendees);
        filterDay.addEventListener('change', filterAttendees);
        filterModality.addEventListener('change', filterAttendees);
        filterOrigin.addEventListener('change', filterAttendees);
        filterType.addEventListener('change', filterAttendees);
        filterHour.addEventListener('change', filterAttendees);

        updateStats(attendees);
        renderTable(attendees);

    </script>
</body>
</html>
"""

@router.get("/dashboard-showroom-2026", response_class=HTMLResponse)
def get_showroom_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    results = db.query(Appointment, Contact).join(
        Contact, Appointment.contact_id == Contact.id
    ).filter(
        Appointment.status == 'CONFIRMED',
        Appointment.datetime >= '2026-07-28 00:00:00',
        Appointment.datetime <= '2026-07-29 23:59:59'
    ).order_by(Appointment.datetime.asc()).all()
    
    contacts_data = []
    
    for a, c in results:
        notes = (a.notes or "").lower() + " " + (c.qualification_notes or "").lower()
        
        # Modalidad
        is_virtual = any(w in notes for w in ["virtual", "espera vip", "lista de espera"])
        modality = "Virtual (Llamada/Meet)" if is_virtual else "Presencial (Showroom Armenia)"
        
        # Origen del Lead
        is_meta = any(w in notes for w in ["meta ads", "campaña", "publicitario", "form_submission", "atribución", "ad id", "ad_id", "adname"])
        origin = "Campaña Formulario (Meta)" if is_meta else "Campaña Directa / Orgánico"
        
        # Perfil cliente
        client_type = "Persona Natural"
        if any(w in notes for w in ["empresa", "inversionista", "desarrollo inmobiliario", "glamping", "hotel"]):
            client_type = "Empresa / Inversionista"
            
        purpose = "Vivienda Propia / Campestre"
        if any(w in notes for w in ["glamping", "hotel", "turismo"]):
            purpose = "Glamping / Hotelería / Turismo"
        elif any(w in notes for w in ["comercial", "oficina"]):
            purpose = "Local Comercial / Oficina"
        elif any(w in notes for w in ["desarrollo", "inmobiliario"]):
            purpose = "Desarrollo Inmobiliario"
            
        # Detección inteligente de Lote (Sí tiene vs No/Buscando)
        has_lote = "No / Buscando"
        positivos = [
            "ya tengo lote", "si tengo lote", "si, ya tengo", "sí, ya tengo", "tengo lote",
            "tiene lote", "tener lote", "tiene un lote", "tener un lote",
            "cuenta con lote", "cuenta con terreno", "posee lote", "posee terreno",
            "lote propio: sí", "lote propio: si", "lote propio (si)", "lote propio (sí)",
            "finca", "terreno propio", "lote propio"
        ]
        negativos = [
            "no tiene lote", "no cuenta con lote", "buscando lote", "no tiene terreno",
            "sin lote", "sin terreno", "no, pero buscando", "no tiene finca", "no cuenta con terreno",
            "no, buscando", "no, pero buscando lote"
        ]
        tiene_mencion_positiva = any(p in notes for p in positivos)
        tiene_contradiccion = any(n in notes for n in negativos)
        if tiene_mencion_positiva and not tiene_contradiccion:
            has_lote = "Sí, ya tiene Lote"
            
        # Ciudad
        city = "Armenia"
        for ct in ["quimbaya", "pereira", "cali", "bogota", "bogotá", "cartago", "bello", "paipa", "circasia", "montenegro"]:
            if ct in notes:
                city = ct.capitalize()
                break
                
        day_name = "Martes 28 de Julio" if a.datetime.day == 28 else "Miércoles 29 de Julio"
        time_str = a.datetime.strftime("%I:%M %p").replace(" 0", " ").strip()
        
        contacts_data.append({
            "contact_id": c.id,
            "name": f"{c.first_name or ''} {c.last_name or ''}".strip() or "Sin nombre",
            "phone": c.phone,
            "email": c.email or "No provisto",
            "city": city,
            "day": day_name,
            "time": time_str,
            "hour_num": a.datetime.hour,
            "modality": modality,
            "client_type": client_type,
            "origin": origin,
            "purpose": purpose,
            "has_lote": has_lote,
            "notes": c.qualification_notes or "Sin notas adicionales."
        })
        
    json_str = json.dumps(contacts_data, ensure_ascii=False, indent=4).replace("<", "\\u003c").replace(">", "\\u003e")
    filled_html = HTML_TEMPLATE.replace("{json_str}", json_str)
    
    return HTMLResponse(content=filled_html)


@router.get("/showroom-citas-json")
def get_showroom_citas_json(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from app.models.base import Message, SenderType, LeadActivityLog

    # Obtener IDs de contactos que enviaron mensaje explicito de confirmacion en el chat
    contact_msgs = db.query(Message.contact_id, Message.content).filter(
        Message.sender_type == SenderType.CONTACT
    ).all()

    confirmed_contact_ids = set()
    for cid, content in contact_msgs:
        txt = (content or "").lower()
        if txt.startswith("¡hola! completé el formulario"):
            continue
        if any(w in txt for w in ["btn_day_mar28", "btn_day_mie29", "btn_confirm", "btn_time", "confirmo", "asistiré", "asistire", "alla estare", "allá estaré", "nos vemos", "sí, confirmar", "si, confirmar", "a las 10", "a las 11", "a las 2", "a las 4", "a las 5", "mañana a las", "miercoles a las"]):
            if not any(neg in txt for neg in ["no puedo", "no podemos", "cancelar", "imposible"]):
                confirmed_contact_ids.add(cid)

    results = db.query(Appointment, Contact).join(
        Contact, Appointment.contact_id == Contact.id
    ).filter(
        Appointment.status == 'CONFIRMED',
        Contact.id.in_(list(confirmed_contact_ids)),
        Appointment.datetime >= '2026-07-28 00:00:00',
        Appointment.datetime <= '2026-07-29 23:59:59'
    ).order_by(Appointment.datetime.asc()).all()
    
    if not results:
        return []

    contacts_data = []
    
    for a, c in results:
        notes = (a.notes or "").lower() + " " + (c.qualification_notes or "").lower()
        is_virtual = any(w in notes for w in ["virtual", "espera vip", "lista de espera"])
        modality = "Virtual (Llamada/Meet)" if is_virtual else "Presencial (Showroom Armenia)"
        is_meta = any(w in notes for w in ["meta ads", "campaña", "publicitario", "form_submission", "atribución", "ad id", "ad_id", "adname"])
        origin = "Campaña Formulario (Meta)" if is_meta else "Campaña Directa / Orgánico"
        client_type = "Persona Natural"
        if any(w in notes for w in ["empresa", "inversionista", "desarrollo inmobiliario", "glamping", "hotel"]):
            client_type = "Empresa / Inversionista"
        purpose = "Vivienda Propia / Campestre"
        if any(w in notes for w in ["glamping", "hotel", "turismo"]):
            purpose = "Glamping / Hotelería / Turismo"
        elif any(w in notes for w in ["comercial", "oficina"]):
            purpose = "Local Comercial / Oficina"
        elif any(w in notes for w in ["desarrollo", "inmobiliario"]):
            purpose = "Desarrollo Inmobiliario"
        
        has_lote = "No / Buscando"
        positivos = [
            "ya tengo lote", "si tengo lote", "si, ya tengo", "sí, ya tengo", "tengo lote",
            "tiene lote", "tener lote", "tiene un lote", "tener un lote",
            "cuenta con lote", "cuenta con terreno", "posee lote", "posee terreno",
            "lote propio: sí", "lote propio: si", "lote propio (si)", "lote propio (sí)",
            "finca", "terreno propio", "lote propio"
        ]
        negativos = [
            "no tiene lote", "no cuenta con lote", "buscando lote", "no tiene terreno",
            "sin lote", "sin terreno", "no, pero buscando", "no tiene finca", "no cuenta con terreno",
            "no, buscando", "no, pero buscando lote"
        ]
        tiene_mencion_positiva = any(p in notes for p in positivos)
        tiene_contradiccion = any(n in notes for n in negativos)
        if tiene_mencion_positiva and not tiene_contradiccion:
            has_lote = "Sí, ya tiene Lote"
            
        city = "Armenia"
        for ct in ["quimbaya", "pereira", "cali", "bogota", "bogotá", "cartago", "bello", "paipa", "circasia", "montenegro"]:
            if ct in notes:
                city = ct.capitalize()
                break
                
        # Evaluación instantánea en memoria O(1)
        reconfirmed = c.id in confirmed_contact_ids
        
        day_name = "Martes 28 de Julio" if a.datetime.day == 28 else "Miércoles 29 de Julio"
        time_str = a.datetime.strftime("%I:%M %p").replace(" 0", " ").strip()
        contacts_data.append({
            "contact_id": c.id,
            "name": f"{c.first_name or ''} {c.last_name or ''}".strip() or "Sin nombre",
            "phone": c.phone,
            "email": c.email or "No provisto",
            "city": city,
            "day": day_name,
            "time": time_str,
            "hour_num": a.datetime.hour,
            "modality": modality,
            "client_type": client_type,
            "origin": origin,
            "purpose": purpose,
            "has_lote": has_lote,
            "reconfirmed": reconfirmed,
            "notes": c.qualification_notes or "Sin notas adicionales."
        })
    return contacts_data
