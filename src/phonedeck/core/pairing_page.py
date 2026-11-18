"""A page that shows the pairing QR code big, with a countdown. It reloads itself, so a new code
shows up by itself. The link is only drawn into the picture, never written as text in the page.
"""

import segno

REFRESH_SECONDS = 2


def render_pairing_page(link: str, seconds_left: float) -> str:
    """The HTML of the pairing page for this link, valid for seconds_left more seconds."""
    qr_picture = segno.make(link, error="l").svg_inline(
        scale=8, border=3, dark="#000000", light="#ffffff"
    )
    milliseconds_left = max(0, int(seconds_left * 1000))
    seconds_shown = max(0, round(seconds_left))  # never a minus sign
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta http-equiv="refresh" content="{REFRESH_SECONDS}" />
    <title>PhoneDeck: scan to pair</title>
    <style>
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #eef0f3;
        color: #15171a;
        font-family: system-ui, sans-serif;
        text-align: center;
      }}
      .card {{ background: #fff; padding: 24px 32px 28px; border-radius: 16px; }}
      svg {{ width: min(70vmin, 520px); height: auto; display: block; margin: 0 auto 12px; }}
      h1 {{ margin: 0 0 4px; font-size: 1.5rem; }}
      p {{ margin: 4px 0; color: #4b5563; }}
      #left {{ font-weight: 600; font-size: 1.2rem; color: #15171a; }}
    </style>
  </head>
  <body>
    <div class="card">
      <h1>PhoneDeck</h1>
      <p>Scan this code with the phone's camera.</p>
      {qr_picture}
      <p id="left">{seconds_shown} seconds left</p>
      <p>The code can be used once. A new one appears when it has been used or has run out.</p>
    </div>
    <script>
      const end = Date.now() + {milliseconds_left};
      const label = document.getElementById("left");
      function tick() {{
        const left = Math.max(0, Math.round((end - Date.now()) / 1000));
        label.textContent = left > 0 ? left + " seconds left" : "Expired. A new code is coming.";
      }}
      tick();
      setInterval(tick, 500);
    </script>
  </body>
</html>
"""
