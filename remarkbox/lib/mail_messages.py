WELCOME_1_TEXT = """
Hello!

Thanks for joining the discussion.

To get reply notifications, you should paste this link into your browser:

 \n{0}\n

This will verify your email and log you in.

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
</head>
  <body>
    <h2>Hello!</h2>

    <p>
    Thanks for joining the discussion.
    </p>

    <p>
    To get reply notifcations, you should click this link:
    </p>

    <p>
    <a href="{1}" style="font-weight: bold;" target="_blank">Click here to verify and log in!</a>
    </p>

    <p style="font-size: .8em;">
    <span style="color: #aaaaaa;">
    You may paste this link into your browser:
    </span>
    <br>
    <br>
    <a href="{1}" style="color: #439fe0; font-weight: normal; text-decoration: none; word-break: break-word;" target="_blank">
    {1}
    </a>
    </p>

    <p>
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

To log in please paste this link into your browser:

 \n{0}\n

Don't forget to check out your notification settings.

Talk to you soon!
"""

WELCOME_2_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>{0}</title>
</head>
  <body>
    <h2>Hello again!</h2>

    <p>
    To log in please click the link below.
    </p>

    <p>
    <a href="{1}" style="font-weight: bold;" target="_blank">Click here to log in!</a>
    </p>

    <p style="font-size: .8em;">
    <span style="color: #aaaaaa;">
    You may paste this link into your browser:
    </span>
    <br>
    <br>
    <a href="{1}" style="color: #439fe0; font-weight: normal; text-decoration: none; word-break: break-word;" target="_blank">
    {1}
    </a>
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
