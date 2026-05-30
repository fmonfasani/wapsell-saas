# Meta WhatsApp — dev setup (test number + ngrok tunnel)

> Goal: receive a real WhatsApp message in your local Waseller webhook **without
> Meta verification, without a paid number, in ~15 minutes**.

## 1. Meta Business + dev App (one-time)

1. [business.facebook.com](https://business.facebook.com) → create a Business
   Portfolio (your name + email).
2. [developers.facebook.com](https://developers.facebook.com) → *My Apps → Create
   App* → **type: Business**.
3. Inside the app → *Add Product* → **WhatsApp** → *Set up*.
4. In *WhatsApp → API Setup* Meta auto-provisions a **test phone number** and a
   temporary access token (24h). You can register up to 5 recipient numbers to
   message them without business verification.

## 2. The 4 things you need to copy into `.env`

In your project root:

```bash
META_APP_SECRET=<Settings → Basic → App Secret (reveal)>
META_VERIFY_TOKEN=<you invent any random string; reuse below>
WHATSAPP_PHONE_NUMBER_ID=<WhatsApp → API Setup → Phone number ID>
KAPSO_GATEWAY_URL=http://localhost:4000   # only matters when Kapso is running
```

The Meta access token isn't in `.env` for Waseller; it's read by the Kapso gateway
service when you wire that in. For now you only need the four above.

## 3. Tunnel localhost to the internet

Meta needs to reach your webhook over **HTTPS**. Two options:

```bash
# Option A: ngrok (free; sign up at ngrok.com once)
ngrok http 8000
# → copy the https URL: https://<random>.ngrok-free.app

# Option B: Cloudflare Tunnel (no signup)
cloudflared tunnel --url http://localhost:8000
```

## 4. Run the Waseller API

```bash
cd D:\Software Development\Porfolio\HermesSell   # (folder still named HermesSell)
make dev                # if you haven't installed deps yet
uvicorn services.api.main:app --reload --port 8000
```

You should see `INFO Uvicorn running on http://0.0.0.0:8000`.

## 5. Register the webhook with Meta

In Meta → *WhatsApp → Configuration → Webhook → Edit*:

- **Callback URL**: `https://<your-tunnel>.ngrok-free.app/webhook`
- **Verify Token**: the same string you put in `META_VERIFY_TOKEN`
- Click **Verify and save** — Meta makes a `GET /webhook?hub.mode=subscribe&...`
  to your URL; Waseller responds with the challenge. If you see ✅ it worked.
- Subscribe to webhook fields: at minimum **`messages`**.

## 6. Wire your tenant to the test number

The webhook routes by `phone_number_id`. Tell Waseller which tenant owns it:

```python
# one-off, e.g. via python -i
from waseller import WasellerClient
c = WasellerClient()
t = c.create_tenant("MyDev", "mydev")
c.tenants.repository.update(
    t.model_copy(update={"whatsapp_phone_number_id": "<your Phone number ID>"})
)
```

## 7. Send yourself a WhatsApp from the test panel

Meta → *WhatsApp → API Setup* → bottom of the page lets you message a recipient
number you added. Send "hola". The Waseller webhook should:

1. verify the HMAC signature → 200,
2. resolve the tenant from `phone_number_id`,
3. remember the message,
4. invoke `lead-qualifier`,
5. (with `InMemoryGateway`) **record** the auto-reply but not send it — the
   wired Kapso adapter is needed for the actual outbound. For local-only smoke,
   `InMemoryGateway` is enough to see the full pipeline run.

## Going beyond test mode

When you graduate to a real number / >5 recipients / production volume:

- Verify your business in Meta Business Manager (upload docs).
- Get a phone number permanently associated to your WABA.
- Replace the 24h temp token with a permanent System User token.
- Swap `InMemoryGateway` for `KapsoGateway(client=httpx.AsyncClient(), base_url="https://your-kapso-host")`.
- TLS in front of your webhook (covered by P13).
