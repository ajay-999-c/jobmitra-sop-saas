"""Real, small PDFs for upload tests; no private or historical document bytes."""

import io

from pypdf import PdfWriter


def valid_pdf():
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(595, 842)
    writer.write(output)
    return output.getvalue()
