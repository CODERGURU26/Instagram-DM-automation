import hmac
import hashlib
import httpx
import os
import json
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Query, Header, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID", "")  # Your IG Business/Creator Account ID
APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET", "")
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
# HELPER FUNCTIONS
# ============================================================

def verify_signature(payload: bytes, signature: str) -> bool:
    """Verifies that the webhook event came from Meta."""
    if not APP_SECRET or not signature:
        return True  # Skip during local testing if APP_SECRET is not set
    
    expected_sig = "sha256=" + hmac.new(
        APP_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected_sig, signature)


async def send_private_dm_reply(comment_id: str, message_text: str):
    """Sends a Private DM to a user who commented on a post or reel."""
    url = f"https://graph.facebook.com/v22.0/{INSTAGRAM_ACCOUNT_ID}/messages"
    
    payload = {
        "recipient": {
            "comment_id": comment_id
        },
        "message": {
            "text": message_text
        }
    }
    
    headers = {
        "Authorization": f"Bearer {INSTAGRAM_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers, timeout=10)
        res_data = response.json()
        
        if response.status_code == 200:
            logger.info("Private DM sent successfully for comment_id: %s", comment_id)
        else:
            logger.error("Failed to send private DM: %s", res_data)

# ============================================================
# ENDPOINTS
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
    return {"status": "healthy"}

@app.get("/instagram/callback")
async def instagram_callback(request: Request):
    code = request.query_params.get("code")

    if not code:
        return JSONResponse(
            content={"status": "error", "message": "No authorization code received"},
            status_code=400
        )

    logger.info("Instagram authorization code received")

    try:
        async with httpx.AsyncClient() as client:
            # FIXED: Correct Graph API OAuth endpoint for IG Business/DM Automation
            response = await client.get(
                "https://graph.facebook.com/v22.0/oauth/access_token",
                params={
                    "client_id": os.getenv("INSTAGRAM_APP_ID"),
                    "client_secret": os.getenv("INSTAGRAM_APP_SECRET"),
                    "redirect_uri": os.getenv("INSTAGRAM_REDIRECT_URI"),
                    "code": code
                },
                timeout=30
            )
            token_data = response.json()

        if response.status_code != 200:
            logger.error("Token exchange failed: %s", token_data)
            return JSONResponse(
                content={"status": "error", "message": "Token exchange failed", "details": token_data},
                status_code=400
            )

        logger.info("Instagram token generated successfully")
        return {
            "status": "success",
            "message": "Token generated successfully. Copy 'access_token' to your .env file.",
            "access_token": token_data.get("access_token")
        }

    except Exception as e:
        logger.exception("Instagram token exchange failed")
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)

@app.get("/webhook")
async def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    logger.info("Webhook verification request received")

    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        logger.info("Webhook verification successful")
        return PlainTextResponse(content=hub_challenge or "", status_code=200)

    logger.warning("Webhook verification failed")
    return PlainTextResponse(content="Verification failed", status_code=403)

@app.post("/webhook")
async def receive_webhook(request: Request, x_hub_signature_256: str | None = Header(default=None)):
    body = await request.body()

    # Optional signature check for security
    if APP_SECRET and not verify_signature(body, x_hub_signature_256 or ""):
        logger.warning("Invalid webhook signature")
        return JSONResponse(content={"status": "unauthorized"}, status_code=401)

    try:
        data = json.loads(body.decode("utf-8"))
        logger.info("INSTAGRAM WEBHOOK EVENT RECEIVED")
        
        await process_instagram_event(data)

        # Meta expects a 200 response to confirm receipt
        return JSONResponse(content={"status": "received"}, status_code=200)

    except json.JSONDecodeError:
        logger.error("Invalid JSON received")
        return JSONResponse(content={"status": "error", "message": "Invalid JSON"}, status_code=400)
    except Exception as e:
        logger.exception("Error processing webhook: %s", str(e))
        # Always return 200 so Meta does not retry/disable webhook
        return JSONResponse(content={"status": "error_handled"}, status_code=200)

# ============================================================
# EVENT PROCESSOR & HANDLERS
# ============================================================

async def process_instagram_event(data: dict):
    entries = data.get("entry", [])

    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            field = change.get("field")
            value = change.get("value", {})

            if field == "comments":
                await handle_comment_event(value)

async def handle_comment_event(comment_data: dict):
    logger.info("COMMENT EVENT RECEIVED: %s", comment_data)

    comment_id = comment_data.get("id")
    text = comment_data.get("text", "").lower()

    # Example Keyword Trigger Logic
    if "link" in text or "info" in text or "send" in text:
        logger.info("Trigger keyword detected in comment ID %s. Sending DM...", comment_id)
        reply_text = "Hey! Thanks for commenting. Here is the link you requested: https://yourwebsite.com"
        await send_private_dm_reply(comment_id, reply_text)

# ============================================================
# SERVER STARTUP
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)