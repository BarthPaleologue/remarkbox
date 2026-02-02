/**
 * Remarkbox Push Notification Service Worker
 *
 * Handles incoming push events and notification clicks.
 * Registered by the push subscription code on the client side.
 */

/* eslint-env serviceworker */

self.addEventListener("push", function (event) {
  var data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data = { title: "Remarkbox", body: event.data.text() };
    }
  }

  var title = data.title || "Remarkbox";
  var options = {
    body: data.body || "You have a new notification.",
    icon: data.icon || "/static/img/remarkbox-icon.png",
    badge: data.badge || "/static/img/remarkbox-icon.png",
    tag: data.tag || "remarkbox-notification",
    data: {
      url: data.url || "/",
    },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();

  var url = "/";
  if (event.notification.data && event.notification.data.url) {
    url = event.notification.data.url;
  }

  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clientList) {
      // Focus existing window if one is open.
      for (var i = 0; i < clientList.length; i++) {
        var client = clientList[i];
        if (client.url === url && "focus" in client) {
          return client.focus();
        }
      }
      // Otherwise open a new window.
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});
