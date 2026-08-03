"""Test of remapping temp-PDF page numbers onto the original ones."""

from pdf_processing.parser import _remap_to_original


def test_remap_page_numbers_block_ids_and_images():
    # temp PDF: pages 1,2 correspond to original pages 3 and 7
    document = {
        "document_id": "temp",
        "document_name": "temp.pdf",
        "pages": [
            {
                "page_number": 1,
                "blocks": [{"block_id": "p1_b01", "type": "text", "text": "a"}],
            },
            {
                "page_number": 2,
                "blocks": [{"block_id": "p2_b03", "type": "text", "text": "b"}],
            },
        ],
    }
    page_images = {1: "imgA", 2: "imgB"}

    _remap_to_original(document, page_images, [3, 7], "ČSN 1.pdf")

    assert document["pages"][0]["page_number"] == 3
    assert document["pages"][0]["blocks"][0]["block_id"] == "p3_b01"
    assert document["pages"][1]["page_number"] == 7
    assert document["pages"][1]["blocks"][0]["block_id"] == "p7_b03"
    assert page_images == {3: "imgA", 7: "imgB"}
    # id/name restored from the original file
    assert document["document_id"] == "csn_1"
    assert document["document_name"] == "ČSN 1.pdf"
