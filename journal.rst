Tue 04 Aug 2020 12:48:06 AM EDT
=====================================

- [ ]: TODO regressions are sad, let's write more functional tests.



Tue 11 Aug 2020 09:50:33 PM EDT
=====================================

- [x]: TODO fix the defect

Found some common errors in prod::

 sudo zgrep UnicodeEncodeError /var/log/syslog.*.gz | wc -l
 223

This was the bad code which didn't support unicode::

 def _reduce_whitespace(text):
     return " ".join(map(str.strip, map(str, text.splitlines())))

Here is the replacement which supports unicode::

 def _reduce_whitespace(text):
     """a way to remove newlines and leading/trailing whitespace per line."""
     return " ".join([line.strip() for line in text.splitlines()])

Check back in a few days to make sure the errors are gone, by running::

 sudo zgrep UnicodeEncodeError /var/log/syslog.*.gz | wc -l
 223

Update: Fixed!::

 fox@remarkbox:~$ date
 Fri Aug 21 16:28:32 EDT 2020

 fox@remarkbox:~$ sudo zgrep UnicodeEncodeError /var/log/syslog.*.gz | wc -l
 1


Tue 11 Aug 2020 09:58:07 PM EDT
=====================================

- [ ]: TODO fix the defect

::

 sudo zgrep "Incorrect padding" /var/log/syslog.*.gz
 214

The fix is maybe removing the premature optimization of "short" uuids.
I made the call, rightfully, to avoid this premature optimization in 
the `make_post_sell` code base after seeing the issues it caused in
Remarkbox.

Here is a snippet of the Traceback::

 Aug 10 10:05:35 remarkbox.com demo.remarkbox.com[12893]:     return get_object_by_id(dbsession, node_id, Node)
 Aug 10 10:05:35 remarkbox.com demo.remarkbox.com[12893]:   File "/www/demo.remarkbox.com/env/lib/python2.7/site-packages/remarkbox/models/meta.py", line 116, in get_object_by_id
 Aug 10 10:05:35 remarkbox.com demo.remarkbox.com[12893]:     object_uuid = id_to_uuid(object_id)
 Aug 10 10:05:35 remarkbox.com demo.remarkbox.com[12893]:   File "/www/demo.remarkbox.com/env/lib/python2.7/site-packages/remarkbox/models/meta.py", line 107, in id_to_uuid
 Aug 10 10:05:35 remarkbox.com demo.remarkbox.com[12893]:     return uuid.UUID(bytes=short_id_to_bytes(the_id))
 Aug 10 10:05:35 remarkbox.com demo.remarkbox.com[12893]:   File "/www/demo.remarkbox.com/env/lib/python2.7/site-packages/remarkbox/models/meta.py", line 80, in short_id_to_bytes
 Aug 10 10:05:35 remarkbox.com demo.remarkbox.com[12893]:     return (short_id + "==").replace("_", "/").replace("-", "+").decode("base64")
 Aug 10 10:05:35 remarkbox.com demo.remarkbox.com[12893]:   File "/usr/lib/python2.7/encodings/base64_codec.py", line 42, in base64_decode
 Aug 10 10:05:35 remarkbox.com demo.remarkbox.com[12893]:     output = base64.decodestring(input)
 Aug 10 10:05:35 remarkbox.com demo.remarkbox.com[12893]:   File "/usr/lib/python2.7/base64.py", line 328, in decodestring
 Aug 10 10:05:35 remarkbox.com demo.remarkbox.com[12893]:     return binascii.a2b_base64(s)

Some quick research suggests maybe a simple fix is appending 3 `=` signs as padding, instead of 2.

I'll try that and check back to see if the errors go away.



Wed 12 Aug 2020 08:54:24 AM EDT
====================================

- [ ]: TODO fix the defect

In this error the user is not authenticated and is trying to click a log-in/verify link
derived from on an embeded thread which has unicode in it's URI path::

 return-to=https://post-tenebras-lire.net/%D0%A7%D0%BE%D1%80%D0%BD%D0%BE%D0%B1%D0%B8%D0%BB%D1%8C/

When the log-in/verify view attempts to `return HTTPFound(return_to)` back to the
`thread_uri` (the page embedding Remarkbx) we get the following exception::

 Aug 10 09:43:27 remarkbox.com demo.remarkbox.com[12893]: [pid: 12909|app: -|req: -/-] 213.55.244.1 (-) {48 vars in 1261 bytes} [Mon Aug 10 09:43:27 2020] GET /join-or-log-in?email=posttenebraslire%40caenevet.net&raw-otp=<removed>&return-to=https://post-tenebras-lire.net/%D0%A7%D0%BE%D1%80%D0%BD%D0%BE%D0%B1%D0%B8%D0%BB%D1%8C/ => generated 0 bytes in 344 msecs (HTTP/1.0 500) 0 headers in 0 bytes (0 switches on core 0)
 Aug 10 09:43:31 remarkbox.com demo.remarkbox.com[12893]: Traceback (most recent call last):
 Aug 10 09:43:31 remarkbox.com demo.remarkbox.com[12893]:     return HTTPFound(return_to)
 Aug 10 09:43:31 remarkbox.com demo.remarkbox.com[12893]:   File "/www/demo.remarkbox.com/env/lib/python2.7/site-packages/pyramid/httpexceptions.py", line 547, in __init__
 Aug 10 09:43:31 remarkbox.com demo.remarkbox.com[12893]:     **kw
 Aug 10 09:43:31 remarkbox.com demo.remarkbox.com[12893]:   File "/www/demo.remarkbox.com/env/lib/python2.7/site-packages/pyramid/httpexceptions.py", line 236, in __init__
 Aug 10 09:43:31 remarkbox.com demo.remarkbox.com[12893]:     Response.__init__(self, status=status, **kw)
 Aug 10 09:43:31 remarkbox.com demo.remarkbox.com[12893]:   File "/www/demo.remarkbox.com/env/lib/python2.7/site-packages/webob/response.py", line 321, in __init__
 Aug 10 09:43:31 remarkbox.com demo.remarkbox.com[12893]:     setattr(self, name, value)
 Aug 10 09:43:31 remarkbox.com demo.remarkbox.com[12893]:   File "/www/demo.remarkbox.com/env/lib/python2.7/site-packages/webob/descriptors.py", line 148, in fset
 Aug 10 09:43:31 remarkbox.com demo.remarkbox.com[12893]:     value = value.encode('latin-1')
 Aug 10 09:43:31 remarkbox.com demo.remarkbox.com[12893]: UnicodeEncodeError: 'latin-1' codec can't encode characters in position 31-39: ordinal not in range(256)
 
The defect is seemingly related to 
the `%` quoted `/%D0%A7%D0%BE%D1%80%D0%BD%D0%BE%D0%B1%D0%B8%D0%BB%D1%8C/`
in the `return-to` url which decodes to `/Чорнобиль/`.

Looking at the webob code this `value = value.encode('latin-1')` is a Python2
compatibility pathway which does not get called for Python3

Reference:
https://github.com/Pylons/webob/blob/ac2d238f50bed7fbbf115818ab7f208b71d7bdca/src/webob/descriptors.py#L147-L155

The obvious answer to this is to upgrade Remarkbox (and MakePostSell) to use
a Python3 environment. Likely this will bring it's own trouble so I'll defer
on fixing this until I have time and energy to tackle that project.


Fri 21 Aug 2020 02:18:55 PM EDT
=======================================

- [X]: TODO tune uwsgi processes/threads 
- [ ]: TODO tune uwsgi processes/threads for maximum performance measured by requests-per-second (RPS) on a semi-random traffic shape.

.. code-block::

 processes = 2
 threads = 8
 enable-threads = True


Fri 21 Aug 2020 02:56:20 PM EDT
====================================

[ ]: TODO adjust terms of service and/or privacy policy

I need to adjust my terms of service to make Remarkbox more useful.

My target market are developers and engineers who like to run their own systems.

My target market cares deeply about page speed and computer performance.

My target market likes numbers and statistics, they want to see growth, they want analytics and metrics, it might be vanity but it's important.

When thinking about their site, I wanted them to think about checking Remarkbx for their stats and comments.

Could Remarkbox become the next Google Analytics? No, but it does need to compete with YouTube studio for example.

Remarkbox should be in a unique situation where we may have a competitive advantage over other metric systems.

Analytics could power the desire of site owners to continue interacting with their user base.

We could use the analytics data to power a goals system (for example measuring blog post throughput, etc)

This data is really important. This data would be made available to site owners as a `.json` file.


Fri 21 Aug 2020 04:24:27 PM EDT
========================================

- [ ]: TODO start tracking `per request analytic data` for auditing the Remarkbox Service, for capacity planning, security, performance, as well as for finding or fueling feature, product, or service growth opportunities.

Additionally this data is also just as important to you, our free and paying customers of the Remarkbox Service.

In order to better serve all of us, and to facilitate a search for a sustainable path forward for Remarkbox to grow into,
I'm proposing alignment of what a `per request analytic datum` looks like::

 id, namespace_id, uri_id, user_id, user_authed, timestamp

With fresh eyes I'm not sure how much energy I want to devote to this idea considering things like Google Analytics already exists.

Maybe just collecting hits per hour and rolled up per day after 2 weeks, whether or not the user was authenticated (so two buckets)
and then a separate table for particular actions like comments per day or something.

Speaking with smarter people than me, they confirmed ElasticSearch would be a good choice as a data store so if I want to do it "right"
that's what I should use.

But if I want to do it "fast / cheap / good enough" storing it in the relational database might be fine until it becomes painful.

If I introduced elasticsearch, I could also have an index for ingesting the embeded pages content (strip out HTML, just plain-text)
and offer full-text search capabilities for static sites. This might cause the dataset to balloon up a lot more than
just `per request analytic data` so this would be a follow up project once we have an elasticsearch cluster.

That said, as a first pass, we could just create a really tiny single node elasticsearch cluster for analytics type data with
many small documents. Additionally these statistics and analytics do not need to have a great uptime SLA. No redundancy and hourly
snapshots such that if the cluster ever went red and needed to be recovered from snapshot, we would only lose an hour of data.

anyways, this isn't a high priority project, it's more of a fun and explority, nice to have rather than a need to have.

Thought I'd get it out of my head and into a journal entry.

https://www.elastic.co/guide/en/elasticsearch/reference/current/glossary.html


Sun Jan 24 06:13:30 PM EST 2021
==================================

After much internal debate, I have decided to YOLO and make Remarkbox pay-what-you-can!

This means by default Namespaces will be created in the production subscription_type such that the use does not need to pay in order to unlock production settings.

TODO:

[x] modify codebase business logic to always create "production" Namespaces by default.
[x] modify codebase business logic to collect pay-what-you-can amount and frequency into a model/table
[x] modify sales funnel, setup sales copy 
[x] modify pricing page to pay-what-you-can
[x] modify meta theme to let the customer know how to pay (paypal.me or /billing)
[x] modify landing page 
[x] migrate all existing development users to production
[ ] create a mailchimp email list dump of all users in the database and send them an email
    letting them know their Namespace was automatically upgraded and unlocked.
[ ] write a script and schedule a cronjob to trigger on the 1st of each month to charge credit cards based on user preferences.
[ ] modify Namespace settings page to remind people to check their "pay-what-you-can" settings. Only display this dialog to people who have never paid or people who have added a new namespace to their account but have not made an update to their pay-what-you-can model.
    code this so it could have various upsells?



Sat Jan 30 03:32:55 PM EST 2021
=====================================

We should build a Remarkbox to matrix bridge. I bet it is a lot like working with slack API by now or if not, maybe I could build that client as open source?


Sat Apr  3 10:40:05 PM EDT 2021
=====================================

this is a useful SQL query to SELECT users who have paid.

::
 SELECT * FROM rb_payment
   INNER JOIN rb_user ON rb_user.id = rb_payment.user_id
 WHERE status = 'completed';




Tue Nov 16 08:40:00 PM EST 2021
====================================

we need to suppliment the magic link with a 6 alpha-numeric one-time-password




Sun Nov 28 01:51:30 PM EST 2021
=====================================


we need to allow Namespace owner/moderator to edit the external uri of a thread.


Fri Dec 24 07:44:13 AM EST 2021
====================================

[] It's time to open the sause and place it into the public domain!

I was nervous but now I AM ready.

I love you all!
