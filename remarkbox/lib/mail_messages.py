WELCOME_1_TEXT = """
Hello!

Thanks for joining the discussion.

Hey there!

Here is the verification code you requested:

 \n{0}\n

Type code into the challenge input field.

What's next?

 * A random username was generated just for you!

Once signed in, you have the power to change your username as well as edit or delete past comments.
You may opt-in to get notified when people reply.

Talk to you soon!
"""

WELCOME_1_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>{0}</title>
<style>
  .otp-code {{
    font-size: 3em;
    font-weight: bold;
    letter-spacing: 0.1em;
    margin: 1em 0;
  }}
</style>
</head>
  <body>
    <h1 class="otp-code">{1}</h1>

    <p>Hello!</p>

    <p>
    Thanks for joining the discussion.
    </p>

    <p>
    Here is the verification code you requested.
    This will verify your email and log you in.
    </p>

    <h3>What's next?</h3>

    <p>
    A random username was generated just for you!
    </p>

    <p>
    Once signed in, you have the power to change your username as well as edit or delete past comments.
    You may opt-in to get notified when people reply.
    </p>

    <p>
    Talk to you soon!
    </p>
  </body>
</html>
"""

WELCOME_2_TEXT = """
Hello again!

Here is the verification code you requested:

 \n{0}\n

Type code into the challenge input field.

Don't forget to check out your notification settings.

Talk to you soon!
"""

WELCOME_2_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>{0}</title>
<style>
  .otp-code {{
    font-size: 3em;
    font-weight: bold;
    letter-spacing: 0.1em;
    margin: 1em 0;
  }}
</style>
</head>
  <body>
    <h1 class="otp-code">{1}</h1>

    <p>Hello again!</p>

    <p>
    Here is the verification code you requested.
    </p>

    <h3>What's next?</h3>

    <p>
    Don't forget to check out your notification settings.
    </p>

    <p>
    Talk to you soon!
    </p>
  </body>
</html>
"""

OPERATOR_HTML = """<!DOCTYPE html>
<html>
<head>
<title>Operator Notification</title>
</head>
  <body>
    <h2>Operator Notification!</h2>
    <p>{}</p>
  </body>
</html>
"""
