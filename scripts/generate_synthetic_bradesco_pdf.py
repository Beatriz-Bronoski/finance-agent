"""Gera um extrato Bradesco completamente ficticio para testes estruturais."""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "samples" / "synthetic" / "bradesco_demo_jul_ago_2026.pdf"


def draw_header(pdf: canvas.Canvas, page_number: int) -> float:
    width, height = A4
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(42, height - 42, "EXTRATO BANCARIO - DADOS TOTALMENTE FICTICIOS")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(42, height - 60, "Agencia: 0000  Conta: 000000-0  Titular: PESSOA TESTE")
    pdf.drawRightString(width - 42, height - 60, f"Pagina {page_number}/2")
    pdf.line(42, height - 70, width - 42, height - 70)
    pdf.setFont("Courier-Bold", 8)
    pdf.drawString(42, height - 86, "Data       Historico/Documento             Credito    Debito       Saldo")
    return height - 102


def draw_rows(
    pdf: canvas.Canvas,
    rows: list[tuple[str, str, str, str, str]],
    page_number: int,
) -> None:
    y = draw_header(pdf, page_number)
    pdf.setFont("Courier", 8)
    for reference, history, credit, debit, balance in rows:
        pdf.drawString(42, y, reference)
        pdf.drawString(130, y, history)
        if credit:
            pdf.drawRightString(414, y, credit)
        if debit:
            pdf.drawRightString(486, y, debit)
        pdf.drawRightString(558, y, balance)
        y -= 17
    pdf.setFont("Helvetica-Oblique", 8)
    pdf.drawString(42, 46, "Documento sintetico. Nao representa conta, pessoa ou transacao real.")


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(OUTPUT), pagesize=A4)
    pdf.setTitle("Extrato Bradesco Ficticio")
    pdf.setAuthor("Finance Agent - dados sinteticos")

    page_one = [
        ("01/07/2026", "SALDO ANTERIOR 0", "", "", "1.500,00"),
        ("02/07/2026", "PIX RECEBIDO TESTE 12345", "250,00", "", "1.750,00"),
        ("84521", "COMPRA LOJA TESTE", "", "80,00", "1.670,00"),
        ("456789", "SAQUE FICTICIO", "", "200,00", "1.470,00"),
        ("9876543", "TRANSFERENCIA TESTE", "", "150,00", "1.320,00"),
        ("2345678", "RENDIMENTO TESTE", "10,00", "", "1.330,00"),
    ]
    draw_rows(pdf, page_one, 1)
    pdf.showPage()

    page_two = [
        ("07/07/2026", "COD. LANC. 0", "", "5,00", "1.325,00"),
        ("AJUSTE FICTICIO", "7654321", "", "45,00", "1.280,00"),
        ("123456789", "PAGAMENTO ID LONGO", "", "20,00", "1.260,00"),
        ("3456789", "CREDITO FICTICIO", "800,00", "", "2.060,00"),
        ("01/08/2026", "COMPRA TESTE 1122334", "", "60,00", "2.000,00"),
        ("2233445", "PIX TESTE", "", "120,00", "1.880,00"),
    ]
    draw_rows(pdf, page_two, 2)
    pdf.save()
    return OUTPUT


if __name__ == "__main__":
    print(build())
