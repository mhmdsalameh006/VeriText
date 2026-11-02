import io
from datetime import datetime
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

NAVY = colors.HexColor('#16243F')
TEAL = colors.HexColor('#087D80')
MUTED = colors.HexColor('#637189')


def make_report(scan, result):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf,pagesize=A4,rightMargin=19*mm,leftMargin=19*mm,
                            topMargin=21*mm,bottomMargin=19*mm)
    st = getSampleStyleSheet()
    st.add(ParagraphStyle(name='BrandX',fontName='Helvetica-Bold',fontSize=21,leading=26,textColor=NAVY,spaceAfter=4))
    st.add(ParagraphStyle(name='SubX',fontName='Helvetica',fontSize=9,leading=13,textColor=MUTED,spaceAfter=12))
    st.add(ParagraphStyle(name='SectionX',fontName='Helvetica-Bold',fontSize=12,leading=16,textColor=NAVY,spaceBefore=16,spaceAfter=8))
    st.add(ParagraphStyle(name='BodyX',fontName='Helvetica',fontSize=9,leading=14,spaceAfter=7))
    st.add(ParagraphStyle(name='SmallX',fontName='Helvetica',fontSize=8,leading=12,textColor=MUTED))
    story = [Paragraph('VeriText  /  Integrity Report',st['BrandX']),
             Paragraph('Evidence-led document review • Generated '+datetime.now().strftime('%Y-%m-%d %H:%M'),st['SubX']),
             Paragraph(escape(scan['title'][:180]),st['SectionX'])]
    sim = result['similarity']
    ai = result['ai']
    details = [
        ['Similarity to indexed sources', f"{sim['similarity_percent']}%" if sim['similarity_percent'] is not None else 'Not assessed'],
        ['Indexed sources available',str(sim['sources_checked'])],
        ['Matched words',str(sim['matched_words'])],
        ['Submitted words',str(sim['word_count'])],
        ['AI writing assessment',escape(ai['classification'])],
        ['AI model score',f"{ai['probability']}%" if ai['probability'] is not None else 'Not assessed'],
    ]
    table = Table(details,colWidths=[77*mm,83*mm],hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#F5F8FB')),
        ('LINEBELOW',(0,0),(-1,-2),.45,colors.HexColor('#DFE5EC')),
        ('TEXTCOLOR',(0,0),(0,-1),MUTED),('TEXTCOLOR',(1,0),(1,-1),NAVY),
        ('FONTNAME',(1,0),(1,-1),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),9),
        ('BOTTOMPADDING',(0,0),(-1,-1),9)
    ]))
    story.append(table)
    story.append(Paragraph('Matched sources', st['SectionX']))
    if sim['sources']:
        for i, source in enumerate(sim['sources'][:12],1):
            url = f" ({escape(source['source_url'][:160])})" if source['source_url'] else ''
            story.append(Paragraph(f"{i}. <b>{escape(source['title'][:130])}</b> — {source['matched_words']} matched words; {source['percent_of_submission']}% of submission{url}",st['BodyX']))
    else:
        story.append(Paragraph('No matching passages found in the currently indexed collection.' if sim['sources_checked'] else 'No reference sources have been indexed.',st['BodyX']))
    story.append(Paragraph('Representative overlaps',st['SectionX']))
    for match in sim['overlaps'][:12]:
        snippet = scan['text'][match['start']:match['end']]
        story.append(Paragraph(f"<b>{escape(match['source_title'][:100])}</b> — {match['matched_words']} words",st['BodyX']))
        story.append(Paragraph(escape(snippet[:450]),st['BodyX']))
    story.append(Paragraph('AI analysis context',st['SectionX']))
    story.append(Paragraph(escape(ai['explanation']),st['BodyX']))
    if ai['model'].get('available'):
        story.append(Paragraph('Held-out evaluation: FPR '+str(ai['model'].get('test_false_positive_rate'))+
                               ', recall '+str(ai['model'].get('test_recall'))+
                               ', sample count '+str(ai['model'].get('test_documents'))+'.',st['BodyX']))
    for item in ai['style']['indicators']:
        story.append(Paragraph(escape(item['label'])+': '+escape(str(item['value']))+' '+escape(item['unit']),st['BodyX']))
    story.append(Spacer(1,12))
    story.append(Paragraph('Interpretation: Source similarity includes properly quoted or cited text. Statistical AI classification cannot establish authorship or identify the originating model. Human review is required for disciplinary decisions. No public-web search is implied by a local-only scan.',st['SmallX']))

    def footer(canvas, document):
        canvas.setFont('Helvetica',8)
        canvas.setFillColor(MUTED)
        canvas.drawString(19*mm,12*mm,'VeriText | Evidence-led document review')
        canvas.drawRightString(192*mm,12*mm,f'Page {document.page}')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buf.getvalue()
