# app/email_service.py
# ============================================================
# Email 發送服務
# 優先使用 Gmail（GMAIL_USER + GMAIL_PASSWORD）
# 未設定 Gmail 則 fallback 到智邦互聯（SMTP_HOST）
# ============================================================
import os
import logging
import aiosmtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)

# Gmail（主要）
GMAIL_USER     = os.environ.get("GMAIL_USER", "")
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD", "")

# 智邦互聯（備用）
SMTP_HOST     = os.environ.get("SMTP_HOST", "mail.url.com.tw")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("SMTP_USER", "info@idiving.com.tw")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM     = os.environ.get("SMTP_FROM", "愛潛水 iDiving <info@idiving.com.tw>")

ATM_BANK_CODE    = os.environ.get("ATM_BANK_CODE", "822")
ATM_BANK_NAME    = os.environ.get("ATM_BANK_NAME", "中國信託 士林分行")
ATM_ACCOUNT_NAME = os.environ.get("ATM_ACCOUNT_NAME", "愛潛水股份有限公司")
ATM_ACCOUNT      = os.environ.get("ATM_ACCOUNT", "285-54009941-9")
DEPOSIT_AMOUNT   = int(os.environ.get("DEPOSIT_AMOUNT", "3000"))
FRONTEND_URL     = os.environ.get("FRONTEND_URL", "https://www.idiving.com.tw")


async def _send(to_email: str, subject: str, body_html: str):
    """送出一封 HTML email（優先 Gmail，fallback 智邦互聯）"""
    use_gmail = bool(GMAIL_USER and GMAIL_PASSWORD)

    msg = EmailMessage()
    msg["From"]    = f"愛潛水 iDiving <{GMAIL_USER}>" if use_gmail else SMTP_FROM
    msg["To"]      = to_email
    msg["Subject"] = subject
    msg.set_content("請使用支援 HTML 的郵件客戶端開啟此信件。")
    msg.add_alternative(body_html, subtype="html")

    if use_gmail:
        host, port, user, pwd = "smtp.gmail.com", 587, GMAIL_USER, GMAIL_PASSWORD
        tls_kwargs = {"start_tls": True}
    else:
        host, port, user, pwd = SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD
        tls_kwargs = {"start_tls": True, "validate_certs": False}

    try:
        await aiosmtplib.send(
            msg,
            hostname=host,
            port=port,
            username=user,
            password=pwd,
            **tls_kwargs,
        )
        logger.info(f"[{'Gmail' if use_gmail else 'SMTP'}] Email sent to {to_email}: {subject}")
    except Exception as e:
        logger.error(f"Email send failed to {to_email}: {e}")
        raise


async def send_payment_request(
    to_email: str,
    name: str,
    course_title: str,
    session_label: str,
    start_date: str,
    end_date: str,
    payment_url: str,
    expire_date: str,
):
    """發送訂金繳費通知 email"""
    subject = f"【愛潛水 iDiving】報名確認 - 請完成訂金繳費"
    body = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto; }}
  .header {{ background: #0077cc; color: #fff; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
  .content {{ padding: 24px; background: #f9f9f9; }}
  .info-box {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; margin: 16px 0; }}
  .info-row {{ display: flex; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }}
  .info-row:last-child {{ border-bottom: none; }}
  .info-label {{ color: #888; width: 100px; flex-shrink: 0; }}
  .info-value {{ color: #222; font-weight: 600; }}
  .btn {{ display: inline-block; background: #0077cc; color: #fff; padding: 14px 32px;
          border-radius: 6px; text-decoration: none; font-size: 16px; font-weight: 700;
          margin: 16px 0; }}
  .warning {{ color: #c00; font-size: 13px; }}
  .footer {{ padding: 16px; text-align: center; color: #999; font-size: 12px; }}
</style>
</head>
<body>
<div class="header"><h2 style="margin:0">愛潛水 iDiving 報名確認</h2></div>
<div class="content">
  <p>親愛的 <strong>{name}</strong> 您好，</p>
  <p>感謝您報名以下課程，您的報名資料已確認，請於 <strong>{expire_date}</strong> 前完成訂金繳費。</p>

  <div class="info-box">
    <div class="info-row">
      <span class="info-label">課程</span>
      <span class="info-value">{course_title}</span>
    </div>
    <div class="info-row">
      <span class="info-label">梯次</span>
      <span class="info-value">{session_label}</span>
    </div>
    <div class="info-row">
      <span class="info-label">日期</span>
      <span class="info-value">{start_date} ～ {end_date}</span>
    </div>
  </div>

  <h3 style="color:#0077cc">訂金繳費資訊</h3>
  <div class="info-box">
    <div class="info-row">
      <span class="info-label">訂金金額</span>
      <span class="info-value" style="color:#c00">NT$ {DEPOSIT_AMOUNT:,}</span>
    </div>
    <div class="info-row">
      <span class="info-label">銀行代號</span>
      <span class="info-value">{ATM_BANK_CODE}</span>
    </div>
    <div class="info-row">
      <span class="info-label">銀行名稱</span>
      <span class="info-value">{ATM_BANK_NAME}</span>
    </div>
    <div class="info-row">
      <span class="info-label">戶名</span>
      <span class="info-value">{ATM_ACCOUNT_NAME}</span>
    </div>
    <div class="info-row">
      <span class="info-label">帳號</span>
      <span class="info-value" style="font-size:18px;letter-spacing:2px">{ATM_ACCOUNT}</span>
    </div>
  </div>

  <p>完成匯款後，請點選下方按鈕填寫匯款資訊，以便我們確認：</p>
  <div style="text-align:center">
    <a href="{payment_url}" class="btn">填寫匯款資訊</a>
  </div>
  <p class="warning">⚠ 此連結將於 {expire_date} 失效，請盡快完成。</p>
</div>
<div class="footer">
  愛潛水 iDiving ｜ 如有疑問請回覆此信件或來電洽詢<br>
  info@idiving.com.tw
</div>
</body>
</html>
"""
    await _send(to_email, subject, body)


async def send_registration_complete(
    to_email: str,
    name: str,
    course_title: str,
    session_label: str,
    start_date: str,
    end_date: str,
):
    """發送報名完成通知 email"""
    subject = f"【愛潛水 iDiving】報名完成通知 🎉"
    body = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto; }}
  .header {{ background: #28a745; color: #fff; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
  .content {{ padding: 24px; background: #f9f9f9; }}
  .info-box {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; margin: 16px 0; }}
  .info-row {{ display: flex; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }}
  .info-row:last-child {{ border-bottom: none; }}
  .info-label {{ color: #888; width: 100px; flex-shrink: 0; }}
  .info-value {{ color: #222; font-weight: 600; }}
  .footer {{ padding: 16px; text-align: center; color: #999; font-size: 12px; }}
</style>
</head>
<body>
<div class="header"><h2 style="margin:0">🎉 報名完成！</h2></div>
<div class="content">
  <p>親愛的 <strong>{name}</strong> 您好，</p>
  <p>我們已確認您的訂金匯款，您的報名已<strong>正式完成</strong>！</p>

  <div class="info-box">
    <div class="info-row">
      <span class="info-label">課程</span>
      <span class="info-value">{course_title}</span>
    </div>
    <div class="info-row">
      <span class="info-label">梯次</span>
      <span class="info-value">{session_label}</span>
    </div>
    <div class="info-row">
      <span class="info-label">日期</span>
      <span class="info-value">{start_date} ～ {end_date}</span>
    </div>
  </div>

  <p>期待您的到來！如有任何問題，歡迎隨時聯繫我們。</p>
</div>
<div class="footer">
  愛潛水 iDiving ｜ info@idiving.com.tw
</div>
</body>
</html>
"""
    await _send(to_email, subject, body)
