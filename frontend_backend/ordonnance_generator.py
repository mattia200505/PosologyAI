"""
Générateur d'ordonnances PDF
Version visuellement améliorée avec design moderne
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER, TA_JUSTIFY
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from io import BytesIO
from datetime import datetime


class OrdonnanceGenerator:
    """Génère une ordonnance médicale au format PDF avec design moderne"""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
        # Couleurs du thème médical
        self.primary_color = colors.HexColor('#3B82F6')  # Bleu médical
        self.secondary_color = colors.HexColor('#8B5CF6')  # Violet
        self.success_color = colors.HexColor('#10B981')  # Vert
        self.text_dark = colors.HexColor('#1F2937')
        self.text_light = colors.HexColor('#6B7280')
        self.bg_light = colors.HexColor('#F3F4F6')
        
        # Dictionnaire de traduction (FR/EN)
        self.text_dict = {
            # En-tête et patient
            'Patient': 'Patient',
            'Âge :': 'Age:',
            'ans': 'years',
            'Médecin Généraliste': 'General Practitioner',
            'Informations du patient': 'Patient Information',
            'Nom complet :': 'Full name:',
            'Symptômes :': 'Symptoms:',
            'Antécédents :': 'Medical history:',
            'Aucun': 'None',
            'Médicaments actuels :': 'Current medications:',
            'Non spécifié': 'Not specified',
            'Diagnostic médical': 'Medical Diagnosis',
            'Diagnostic Principal Probable': 'Probable Primary Diagnosis',
            'Prescription médicamenteuse': 'Drug Prescription',
            'Aucun médicament prescrit': 'No medication prescribed',
            'Médicament non spécifié': 'Unspecified medication',
            'Posologie à déterminer par le médecin': 'Dosage to be determined by the doctor',
            'Posologie :': 'Dosage:',
            'Durée :': 'Duration:',
            'Recommandations médicales': 'Medical Recommendations',
            'Suivez les conseils du médecin.': 'Follow the doctor\'s advice.',
            'Signature et Cachet du Médecin': 'Doctor\'s Signature and Stamp',
        }
    
    def _setup_custom_styles(self):
        """Configure les styles personnalisés pour l'ordonnance"""
        
        # Style pour le nom du docteur
        self.styles.add(ParagraphStyle(
            name='DocteurNom',
            parent=self.styles['Heading1'],
            fontSize=22,
            textColor=colors.HexColor('#3B82F6'),
            spaceAfter=4,
            alignment=TA_LEFT,
            fontName='Helvetica-Bold'
        ))
        
        # Style pour les détails du docteur
        self.styles.add(ParagraphStyle(
            name='DocteurDetails',
            parent=self.styles['Normal'],
            fontSize=11,
            textColor=colors.HexColor('#6B7280'),
            spaceAfter=2,
            alignment=TA_LEFT
        ))
        
        # Style pour les informations patient
        self.styles.add(ParagraphStyle(
            name='PatientInfo',
            parent=self.styles['Normal'],
            fontSize=11,
            textColor=colors.HexColor('#1F2937'),
            spaceAfter=3,
            alignment=TA_RIGHT
        ))
        
        # Style pour les titres de section avec icône
        self.styles.add(ParagraphStyle(
            name='SectionTitle',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#3B82F6'),
            spaceAfter=8,
            spaceBefore=8,
            alignment=TA_LEFT,
            fontName='Helvetica-Bold'
        ))
        
        # Style pour le texte des sections
        self.styles.add(ParagraphStyle(
            name='SectionText',
            parent=self.styles['Normal'],
            fontSize=11,
            textColor=colors.HexColor('#1F2937'),
            spaceAfter=6,
            leading=16,
            alignment=TA_LEFT
        ))
        
        # Style pour les médicaments
        self.styles.add(ParagraphStyle(
            name='MedicationName',
            parent=self.styles['Normal'],
            fontSize=12,
            textColor=colors.HexColor('#1F2937'),
            fontName='Helvetica-Bold',
            spaceAfter=3
        ))
        
        # Style pour la posologie
        self.styles.add(ParagraphStyle(
            name='Posologie',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#6B7280'),
            spaceAfter=2,
            leftIndent=15
        ))
    
    def generate(self, patient_data, diagnostic_data, medications_data, doctor_data=None, language='fr'):
        """
        Génère l'ordonnance PDF avec design moderne
        
        Args:
            patient_data: dict avec {name, age, symptoms, medical_history, current_medications}
            diagnostic_data: dict avec {diagnostic_principal, diagnostic_differentiel, recommandations}
            medications_data: list de dicts avec {title, posologie, duration, etc}
            doctor_data: dict avec {name, specialty, address, city} (optionnel)
            language: 'fr' ou 'en' pour la langue du PDF
        
        Returns:
            BytesIO contenant le PDF généré
        """
        # Données du médecin par défaut
        if doctor_data is None:
            if language == 'en':
                doctor_data = {
                    'name': 'Dr. Mattia Checchia',
                    'specialty': 'General Practitioner',
                    'address': '68 Rue Velpeau',
                    'city': '92160 Antony'
                }
            else:
                doctor_data = {
                    'name': 'Dr. Mattia Checchia',
                    'specialty': 'Médecin Généraliste',
                    'address': '68 Rue Velpeau',
                    'city': '92160 Antony'
                }
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=30*mm,
            leftMargin=30*mm,
            topMargin=25*mm,
            bottomMargin=25*mm
        )
        
        # Construire le contenu
        story = []
        
        # ========== EN-TÊTE AVEC DESIGN MODERNE ==========
        header_data = [
            [
                Paragraph(f'<font size=22 color="#3B82F6"><b>{doctor_data.get("name", "Dr. Mattia Checchia")}</b></font>', self.styles['Normal']),
                Paragraph(f'<font size=11 color="#6B7280"><b>Patient</b></font><br/>'
                         f'<font size=11 color="#1F2937">{patient_data.get("name", "Non spécifié")}</font><br/>'
                         f'<font size=10 color="#6B7280">Âge : {patient_data.get("age", "Non spécifié")} ans</font>',
                         self.styles['Normal'])
            ],
            [
                Paragraph(f'<font size=10 color="#6B7280">{doctor_data.get("specialty", "Médecin Généraliste")}<br/>'
                         f'{doctor_data.get("address", "68 Rue Velpeau")}<br/>'
                         f'{doctor_data.get("city", "92160 Antony")}</font>', self.styles['Normal']),
                Paragraph(f'<font size=10 color="#6B7280">{doctor_data.get("city", "Antony").split()[0]}, le {datetime.now().strftime("%d/%m/%Y")}</font>',
                         self.styles['Normal'])
            ]
        ]
        
        header_table = Table(header_data, colWidths=[270, 270])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 15))
        
        # Ligne de séparation colorée
        story.append(self._create_colored_separator())
        story.append(Spacer(1, 15))
        
        # ========== INFORMATIONS DU PATIENT (CARD STYLE) ==========
        if language == 'en':
            patient_section_title = '📋 PATIENT INFORMATION'
        else:
            patient_section_title = '📋 INFORMATIONS DU PATIENT'
        story.append(self._create_section_header(patient_section_title, self.primary_color))
        
        # Labels traduction selon la langue
        if language == 'en':
            label_name = 'Full name:'
            label_age = 'Age:'
            label_age_unit = 'years'
            label_symptoms = 'Symptoms:'
            label_history = 'Medical history:'
            label_medications = 'Current medications:'
            label_none = 'None'
            label_not_spec = 'Not specified'
        else:
            label_name = 'Nom complet :'
            label_age = 'Âge :'
            label_age_unit = 'ans'
            label_symptoms = 'Symptômes :'
            label_history = 'Antécédents :'
            label_medications = 'Médicaments actuels :'
            label_none = 'Aucun'
            label_not_spec = 'Non spécifié'
        
        patient_info_data = [
            [label_name, patient_data.get('name', label_not_spec)],
            [label_age, f"{patient_data.get('age', label_not_spec)} {label_age_unit}"],
            [label_symptoms, patient_data.get('symptoms', label_not_spec)],
            [label_history, patient_data.get('medical_history', label_none)],
            [label_medications, patient_data.get('current_medications', label_none)]
        ]
        
        patient_table = Table(patient_info_data, colWidths=[120, 390])
        patient_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), self.bg_light),
            ('TEXTCOLOR', (0, 0), (0, -1), self.text_dark),
            ('TEXTCOLOR', (1, 0), (1, -1), self.text_light),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ]))
        story.append(patient_table)
        story.append(Spacer(1, 20))
        
        # ========== DIAGNOSTIC (AVEC ICÔNE) ==========
        if language == 'en':
            diagnostic_section_title = '🔍 MEDICAL DIAGNOSIS'
            diag_prob_label = '<b><font size=11 color="#8B5CF6">Probable Primary Diagnosis</font></b>'
        else:
            diagnostic_section_title = '🔍 DIAGNOSTIC MÉDICAL'
            diag_prob_label = '<b><font size=11 color="#8B5CF6">Diagnostic Principal Probable</font></b>'
        story.append(self._create_section_header(diagnostic_section_title, self.secondary_color))
        
        # Extraire UNIQUEMENT le diagnostic principal probable
        diagnostic_text = diagnostic_data.get('diagnostic_principal', 'Diagnostic non spécifié')
        
        # Parser pour extraire juste la partie "Diagnostic principal probable:**"
        diagnostic_probable = ''
        if '**Diagnostic principal probable:**' in diagnostic_text:
            # Extraire entre "**Diagnostic principal probable:**" et "**Explication IA:**"
            start_marker = '**Diagnostic principal probable:**'
            end_marker = '**Explication IA:**'
            
            start_idx = diagnostic_text.find(start_marker)
            end_idx = diagnostic_text.find(end_marker)
            
            if start_idx != -1:
                if end_idx != -1:
                    diagnostic_probable = diagnostic_text[start_idx + len(start_marker):end_idx].strip()
                else:
                    # Si pas d'explication IA, prendre jusqu'au prochain **
                    remaining_text = diagnostic_text[start_idx + len(start_marker):]
                    next_marker_idx = remaining_text.find('**', 2)  # Trouver le prochain **
                    if next_marker_idx != -1:
                        diagnostic_probable = remaining_text[:next_marker_idx].strip()
                    else:
                        diagnostic_probable = remaining_text.strip()
        else:
            # Fallback: utiliser le texte complet
            diagnostic_probable = diagnostic_text
        
        # Nettoyer le diagnostic (enlever les ** restants)
        diagnostic_probable = diagnostic_probable.replace('**', '').strip()
        
        # Afficher le diagnostic principal seulement
        diag_data = [[Paragraph(f'{diag_prob_label}<br/><br/>{diagnostic_probable}', 
                                self.styles['SectionText'])]]
        diag_table = Table(diag_data, colWidths=[510])
        diag_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#EEF2FF')),
            ('TEXTCOLOR', (0, 0), (-1, -1), self.text_dark),
            ('LEFTPADDING', (0, 0), (-1, -1), 15),
            ('RIGHTPADDING', (0, 0), (-1, -1), 15),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BOX', (0, 0), (-1, -1), 2, colors.HexColor('#8B5CF6')),
        ]))
        story.append(diag_table)
        
        story.append(Spacer(1, 20))
        
        # ========== PRESCRIPTION (STYLE CARDS) ==========
        if language == 'en':
            prescription_section_title = '💊 DRUG PRESCRIPTION'
            no_meds_text = 'No medication prescribed'
        else:
            prescription_section_title = '💊 PRESCRIPTION MÉDICAMENTEUSE'
            no_meds_text = 'Aucun médicament prescrit'
        story.append(self._create_section_header(prescription_section_title, self.success_color))
        
        if medications_data and len(medications_data) > 0:
            for idx, med in enumerate(medications_data, 1):
                med_name = med.get('title', 'Médicament non spécifié')
                posologie = med.get('posologie', 'Posologie à déterminer par le médecin')
                duration = med.get('duration', '')
                
                # Traduire le contenu du médicament si anglais
                if language == 'en':
                    posologie = self._translate_medication_text(posologie, language)
                    duration = self._translate_medication_text(duration, language)
                
                # Carte de médicament
                posologie_label = 'Dosage:' if language == 'en' else 'Posologie :'
                duration_label = 'Duration:' if language == 'en' else 'Durée :'
                
                med_content = f'<b><font size=12 color="#1F2937">{idx}. {med_name}</font></b><br/>'
                med_content += f'<font size=10 color="#6B7280">■■ {posologie_label} {posologie}</font>'
                if duration:
                    med_content += f'<br/><font size=10 color="#6B7280">■■ {duration_label} {duration}</font>'
                
                med_data = [[Paragraph(med_content, self.styles['Normal'])]]
                med_table = Table(med_data, colWidths=[510])
                
                # Couleur alternée pour chaque médicament
                bg_color = colors.HexColor('#F0FDF4') if idx % 2 == 1 else colors.HexColor('#ECFDF5')
                
                med_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), bg_color),
                    ('LEFTPADDING', (0, 0), (-1, -1), 15),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 15),
                    ('TOPPADDING', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                    ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#10B981')),
                ]))
                story.append(med_table)
                story.append(Spacer(1, 8))
        else:
            story.append(Paragraph(f'<i>{no_meds_text}</i>', self.styles['SectionText']))
        
        story.append(Spacer(1, 20))
        
        # ========== RECOMMANDATIONS (AVEC ICÔNE) ==========
        if language == 'en':
            recommendations_section_title = '⚕️ MEDICAL RECOMMENDATIONS'
            rec_label_text = '<b><font size=11 color="#F59E0B">Medical Recommendations</font></b>'
        else:
            recommendations_section_title = '⚕️ RECOMMANDATIONS MÉDICALES'
            rec_label_text = '<b><font size=11 color="#F59E0B">Recommandations Médicales</font></b>'
        story.append(self._create_section_header(recommendations_section_title, colors.HexColor('#F59E0B')))
        
        recommandations_default = 'Suivez les conseils du médecin.' if language == 'fr' else "Follow your doctor's advice."
        recommandations_text = diagnostic_data.get('recommandations', recommandations_default)
        
        # Formatter les recommandations avec des puces et retours à la ligne
        import re
        
        # Essayer plusieurs méthodes de parsing
        phrases = []
        
        # Méthode 1: Split sur les points suivis d'une espace ou majuscule
        if '.' in recommandations_text:
            phrases = re.split(r'(?<=[.!?])\s+(?=[A-Z])', recommandations_text)
        # Méthode 2: Split sur les majuscules si pas de points (phrases collées)
        else:
            # Détecter les débuts de phrases (majuscule après minuscule)
            phrases = re.split(r'(?<=[a-zé)])(?=\s*[A-Z])', recommandations_text)
        
        # Méthode 3: Si toujours rien, essayer de détecter par mots-clés communs
        if len(phrases) <= 1:
            # Chercher des patterns comme "Respecter", "Prendre", "Suivre", "Consulter", etc.
            if language == 'en':
                keywords = ['Respect', 'Take', 'Follow', 'Consult', 'Avoid', 'Monitor', 'Drink', 'Rest']
            else:
                keywords = ['Respecter', 'Prendre', 'Suivre', 'Consulter', 'Éviter', 'Surveiller', 'Boire', 'Repos']
            temp_phrases = []
            current_phrase = ''
            words = recommandations_text.split()
            
            for word in words:
                if word in keywords and current_phrase:
                    temp_phrases.append(current_phrase.strip())
                    current_phrase = word
                else:
                    current_phrase += ' ' + word
            
            if current_phrase:
                temp_phrases.append(current_phrase.strip())
            
            if len(temp_phrases) > 1:
                phrases = temp_phrases
        
        # Créer une liste à puces
        recommandations_formatted = ''
        for phrase in phrases:
            phrase = phrase.strip()
            if phrase:
                # Nettoyer la phrase
                phrase = phrase.rstrip('.,!?')
                recommandations_formatted += f'• {phrase}<br/><br/>'
        
        # Si pas de formatage réussi, afficher tel quel avec puce unique
        if not recommandations_formatted:
            recommandations_formatted = f'• {recommandations_text}'
        
        rec_data = [[Paragraph(recommandations_formatted, self.styles['SectionText'])]]
        rec_table = Table(rec_data, colWidths=[510])
        rec_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFFBEB')),
            ('TEXTCOLOR', (0, 0), (-1, -1), self.text_dark),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor('#F59E0B')),
        ]))
        story.append(rec_table)
        
        story.append(Spacer(1, 30))
        
        # ========== SIGNATURE ==========
        story.append(Spacer(1, 20))
        if language == 'en':
            signature_text = "Doctor's Signature and Stamp"
        else:
            signature_text = 'Signature et Cachet du Médecin'
        signature_data = [
            [Paragraph(f'<font size=10 color="#6B7280">{signature_text}</font>', self.styles['Normal'])]
        ]
        sig_table = Table(signature_data, colWidths=[510])
        sig_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('LINEABOVE', (0, 0), (-1, 0), 1, self.text_light),
            ('TOPPADDING', (0, 0), (-1, -1), 30),
        ]))
        story.append(sig_table)
        
        # Générer le PDF
        doc.build(story)
        buffer.seek(0)
        return buffer
    
    def _translate_medication_text(self, text, language='fr'):
        """
        Traduit le contenu des médicaments (posologie, durée) selon la langue
        """
        if language != 'en' or not text:
            return text
        
        # Dictionnaire des traductions pour le contenu médical
        translations = {
            # Fréquences
            'une fois par jour': 'once daily',
            '1 fois par jour': '1 time per day',
            'deux fois par jour': 'twice daily',
            '2 fois par jour': '2 times per day',
            'trois fois par jour': '3 times per day',
            'le matin': 'in the morning',
            'l\'après-midi': 'in the afternoon',
            'le soir': 'in the evening',
            'la nuit': 'at night',
            'tous les jours': 'daily',
            'tous les 2 jours': 'every 2 days',
            'tous les 3 jours': 'every 3 days',
            # Durées
            'jour': 'day',
            'jours': 'days',
            'semaine': 'week',
            'semaines': 'weeks',
            'mois': 'month',
            'mois': 'months',
            # Dosage
            'mg': 'mg',
            'ml': 'ml',
            'comprimé': 'tablet',
            'comprimés': 'tablets',
            'gélule': 'capsule',
            'gélules': 'capsules',
            'cuillère à café': 'teaspoon',
            'cuillère à soupe': 'tablespoon',
            'gouttes': 'drops',
            'pendant': 'for',
            'après les repas': 'after meals',
            'avant les repas': 'before meals',
            'avec de l\'eau': 'with water',
        }
        
        result = text
        for fr, en in translations.items():
            result = result.replace(fr.lower(), en)
        
        return result
    
    def _create_section_header(self, title, color):
        """Crée un en-tête de section stylisé"""
        data = [[Paragraph(f'<b>{title}</b>', self.styles['Normal'])]]
        table = Table(data, colWidths=[510])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), color),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 13),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        return table
    
    def _create_colored_separator(self):
        """Crée une ligne de séparation colorée dégradée"""
        line_table = Table([['']], colWidths=[540])
        line_table.setStyle(TableStyle([
            ('LINEABOVE', (0, 0), (-1, 0), 3, self.primary_color),
        ]))
        return line_table
