from fastapi import APIRouter

from api.v1.ppt.endpoints.chart_capture import CHART_CAPTURE_ROUTER
from api.v1.ppt.endpoints.chat import CHAT_ROUTER
from api.v1.ppt.endpoints.feedback import FEEDBACK_ROUTER
from api.v1.ppt.endpoints.files import FILES_ROUTER
from api.v1.ppt.endpoints.icons import ICONS_ROUTER
from api.v1.ppt.endpoints.images import IMAGES_ROUTER
from api.v1.ppt.endpoints.outlines import OUTLINES_ROUTER
from api.v1.ppt.endpoints.slide import SLIDE_ROUTER
from api.v1.ppt.endpoints.table_capture import TABLE_CAPTURE_ROUTER
from api.v1.ppt.endpoints.template import TEMPLATE_ROUTER
from api.v1.ppt.endpoints.presentation import PRESENTATION_ROUTER


API_V1_PPT_ROUTER = APIRouter(prefix="/api/v1/ppt")

API_V1_PPT_ROUTER.include_router(FILES_ROUTER)
API_V1_PPT_ROUTER.include_router(OUTLINES_ROUTER)
API_V1_PPT_ROUTER.include_router(SLIDE_ROUTER)
API_V1_PPT_ROUTER.include_router(IMAGES_ROUTER)
API_V1_PPT_ROUTER.include_router(ICONS_ROUTER)
API_V1_PPT_ROUTER.include_router(PRESENTATION_ROUTER)
API_V1_PPT_ROUTER.include_router(CHART_CAPTURE_ROUTER)
API_V1_PPT_ROUTER.include_router(TABLE_CAPTURE_ROUTER)
API_V1_PPT_ROUTER.include_router(CHAT_ROUTER)
API_V1_PPT_ROUTER.include_router(TEMPLATE_ROUTER)
API_V1_PPT_ROUTER.include_router(FEEDBACK_ROUTER)
