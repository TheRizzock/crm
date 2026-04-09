from dotenv import load_dotenv
import resend
import os

load_dotenv()


resend.api_key = os.getenv("RESEND_API_KEY")


def send_template_email(template, first_name, email_address):

    #
    params = {
        "from": "Dan Kowalsky <dan@dankowalsky.com>",
        "to": [email_address],
        # "subject": "Quick question",
        "template": {
            "id": template,
            # Variables must match EXACTLY (case-sensitive!)
            "variables": {
                "FIRST_NAME": first_name,
            },
        },
    }

    resend.Emails.send(params)

if __name__ == "__main__":
    send_template_email("90376431-09d5-4e5d-8981-24a072db23f5", "Mac", "dkowalsky7@gmail.com")