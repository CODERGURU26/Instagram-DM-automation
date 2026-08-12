import httpx
import os
import json
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Query
from fastapi.responses import PlainTextResponse, JSONResponse


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")

PORT = int(os.getenv("PORT", "8000"))


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("instagram_dm_bot")


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="Instagram Comment DM Bot",
    description="Instagram webhook automation server",
    version="1.0.0"
)


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
async def home():
    return {
        "status": "online",
        "service": "Instagram Comment DM Bot",
        "webhook": "/webhook"
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }

@app.get("/instagram/callback")
async def instagram_callback(request: Request):
    code = request.query_params.get("code")

    if not code:
        return JSONResponse(
            content={
                "status": "error",
                "message": "No authorization code received"
            },
            status_code=400
        )

    logger.info("Instagram authorization code received")

    try:
        async with httpx.AsyncClient() as client:

            response = await client.post(
                "https://api.instagram.com/oauth/access_token",
                data={
                    "client_id": os.getenv("INSTAGRAM_APP_ID"),
                    "client_secret": os.getenv("INSTAGRAM_APP_SECRET"),
                    "grant_type": "authorization_code",
                    "redirect_uri": os.getenv("INSTAGRAM_REDIRECT_URI"),
                    "code": code
                },
                timeout=30
            )

            token_data = response.json()

        logger.info(
            "Instagram token exchange response received"
        )

        if response.status_code != 200:
            logger.error(
                "Token exchange failed: %s",
                token_data
            )

            return JSONResponse(
                content={
                    "status": "error",
                    "message": "Token exchange failed",
                    "details": token_data
                },
                status_code=400
            )

        access_token = token_data.get("access_token")
        user_id = token_data.get("user_id")

        logger.info(
            "Instagram token generated successfully"
        )

        # IMPORTANT:
        # Do not print the actual access token in logs.

        return {
            "status": "success",
            "message": "Instagram access token generated successfully",
            "user_id": user_id,
            "access_token": access_token
        }

    except Exception as e:

        logger.exception(
            "Instagram token exchange failed"
        )

        return JSONResponse(
            content={
                "status": "error",
                "message": str(e)
            },
            status_code=500
        )

# ============================================================
# META WEBHOOK VERIFICATION
# ============================================================

@app.get("/webhook")
async def verify_webhook(
    hub_mode: str | None = Query(
        default=None,
        alias="hub.mode"
    ),
    hub_verify_token: str | None = Query(
        default=None,
        alias="hub.verify_token"
    ),
    hub_challenge: str | None = Query(
        default=None,
        alias="hub.challenge"
    ),
):
    """
    Meta sends a GET request to verify the webhook.

    Meta expects:
        hub.mode
        hub.verify_token
        hub.challenge

    If our VERIFY_TOKEN matches, we return hub.challenge.
    """

    logger.info("Webhook verification request received")

    logger.info(
        "hub.mode=%s",
        hub_mode
    )

    if (
        hub_mode == "subscribe"
        and hub_verify_token == VERIFY_TOKEN
    ):
        logger.info("Webhook verification successful")

        return PlainTextResponse(
            content=hub_challenge or "",
            status_code=200
        )

    logger.warning("Webhook verification failed")

    return PlainTextResponse(
        content="Verification failed",
        status_code=403
    )


# ============================================================
# INSTAGRAM WEBHOOK EVENT RECEIVER
# ============================================================

@app.post("/webhook")
async def receive_webhook(request: Request):
    """
    Receives webhook events from Meta/Instagram.
    """

    try:
        data = await request.json()

        logger.info("=" * 60)
        logger.info("INSTAGRAM WEBHOOK EVENT RECEIVED")
        logger.info("=" * 60)

        logger.info(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False
            )
        )

        logger.info("=" * 60)

        # ----------------------------------------------------
        # Process webhook
        # ----------------------------------------------------

        await process_instagram_event(data)

        # Meta expects a successful response.
        return JSONResponse(
            content={
                "status": "received"
            },
            status_code=200
        )

    except json.JSONDecodeError:
        logger.error("Invalid JSON received")

        return JSONResponse(
            content={
                "status": "error",
                "message": "Invalid JSON"
            },
            status_code=400
        )

    except Exception as e:
        logger.exception(
            "Error processing webhook: %s",
            str(e)
        )

        # Return 200 only when appropriate for Meta's webhook
        # retry behavior. During development we expose the error.
        return JSONResponse(
            content={
                "status": "error"
            },
            status_code=500
        )


# ============================================================
# INSTAGRAM EVENT PROCESSOR
# ============================================================

async def process_instagram_event(data: dict):
    """
    Processes incoming Instagram webhook events.

    We will expand this function after we confirm the exact
    webhook payload Meta sends for Reel comments.
    """

    logger.info("Processing Instagram event...")

    # --------------------------------------------------------
    # Basic event inspection
    # --------------------------------------------------------

    object_type = data.get("object")

    logger.info(
        "Object type: %s",
        object_type
    )

    entries = data.get("entry", [])

    if not entries:
        logger.info("No entries found in webhook payload")
        return

    for entry in entries:

        logger.info(
            "Entry received: %s",
            json.dumps(
                entry,
                indent=2,
                ensure_ascii=False
            )
        )

        changes = entry.get("changes", [])

        for change in changes:

            field = change.get("field")
            value = change.get("value", {})

            logger.info(
                "Webhook field: %s",
                field
            )

            # ------------------------------------------------
            # COMMENT EVENT
            # ------------------------------------------------

            if field == "comments":

                logger.info(
                    "Instagram comment event detected!"
                )

                await handle_comment_event(value)

            # ------------------------------------------------
            # MESSAGE EVENT
            # ------------------------------------------------

            elif field == "messages":

                logger.info(
                    "Instagram message event detected!"
                )

                await handle_message_event(value)

            else:

                logger.info(
                    "Unhandled webhook field: %s",
                    field
                )


# ============================================================
# COMMENT HANDLER
# ============================================================

async def handle_comment_event(comment_data: dict):
    """
    Handles an Instagram comment.

    Eventually this function will:

        1. Identify the Reel/post
        2. Identify the commenter
        3. Read the comment
        4. Apply automation rules
        5. Send a private reply/DM
    """

    logger.info("=" * 50)
    logger.info("COMMENT EVENT")
    logger.info("=" * 50)

    logger.info(
        "Comment data:"
    )

    logger.info(
        json.dumps(
            comment_data,
            indent=2,
            ensure_ascii=False
        )
    )

    # --------------------------------------------------------
    # TODO:
    # Send private reply to commenter
    # --------------------------------------------------------

    logger.info(
        "Comment received. DM functionality not enabled yet."
    )


# ============================================================
# MESSAGE HANDLER
# ============================================================

async def handle_message_event(message_data: dict):
    """
    Handles incoming Instagram messages.

    This will be useful later if we want users to reply
    to the automated DM and continue the conversation.
    """

    logger.info("=" * 50)
    logger.info("MESSAGE EVENT")
    logger.info("=" * 50)

    logger.info(
        json.dumps(
            message_data,
            indent=2,
            ensure_ascii=False
        )
    )


# ============================================================
# SERVER STARTUP
# ============================================================

@app.on_event("startup")
async def startup_event():

    logger.info("=" * 60)
    logger.info("Instagram Comment DM Bot starting...")
    logger.info("=" * 60)

    if VERIFY_TOKEN:
        logger.info("VERIFY_TOKEN loaded successfully")
    else:
        logger.warning(
            "VERIFY_TOKEN is missing from .env"
        )

    if INSTAGRAM_ACCESS_TOKEN:
        logger.info(
            "Instagram access token loaded"
        )
    else:
        logger.info(
            "Instagram access token not configured yet"
        )

    logger.info(
        "Webhook endpoint: /webhook"
    )

    logger.info("=" * 60)


# ============================================================
# RUN DIRECTLY
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=True
    )