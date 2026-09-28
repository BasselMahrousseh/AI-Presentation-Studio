from fastapi import APIRouter, File, UploadFile

from templates.pptx_color_extraction import (
    PptxColorPaletteResponse,
    extract_pptx_color_palette_handler,
)


# Only the colour-palette extraction survives from the old template system: the new-deck page
# restyles a Standard (Smart) deck with the palette of an attached reference .pptx.
TEMPLATE_ROUTER = APIRouter(prefix="/template", tags=["Templates"])


@TEMPLATE_ROUTER.post(
    "/extract-color-palette",
    response_model=PptxColorPaletteResponse,
)
async def extract_pptx_color_palette(
    pptx_file: UploadFile = File(..., description="PPTX file to extract a color palette from"),
):
    return await extract_pptx_color_palette_handler(pptx_file=pptx_file)
