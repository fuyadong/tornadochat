#!/usr/bin/env python3
#
# Copyright 2009 Facebook
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import logging
import tornado.auth
import tornado.escape
import tornado.ioloop
import tornado.httpserver
import tornado.options
import tornado.web
import os.path
import uuid

from tornado.options import define, options

define("port", default=8888, help="run on the given port", type=int)

online_users = set()

class Application(tornado.web.Application):
  def __init__(self):
    handlers = [
      (r"/", MainHandler),
      (r"/auth/login", AuthLoginHandler),
      (r"/auth/logout", AuthLogoutHandler),
      (r"/a/message/new", MessageNewHandler),
      (r"/a/message/updates", MessageUpdatesHandler),
    ]
    settings = dict(
      cookie_secret="43oETzKXQAGaYdkL5gEmGeJJFuYh7EQnp2XdTP1o/Vo=",
      login_url="/auth/login",
      template_path=os.path.join(os.path.dirname(__file__), "templates"),
      static_path=os.path.join(os.path.dirname(__file__), "static"),
      xsrf_cookies=True,
      autoescape="xhtml_escape",
      debug=True,
    )
    tornado.web.Application.__init__(self, handlers, **settings)

class BaseHandler(tornado.web.RequestHandler):
  def get_current_user(self):
    user = tornado.escape.to_unicode(self.get_secure_cookie("user"))
    if not user:
      return None
    return user

  def initialize(self):
    if self.current_user:
      online_users.add(self.current_user)

class MainHandler(BaseHandler):
  @tornado.web.authenticated
  def get(self):
    self.render("index.html", messages=MessageMixin.cache,
                name=self.current_user)

class MessageMixin(object):
  waiters = []
  cache = []
  cache_size = 200

  def wait_for_messages(self, callback, cursor=None):
    cls = MessageMixin
    if cursor:
      index = 0
      for i in range(len(cls.cache)):
        index = len(cls.cache) - i - 1
        if cls.cache[index]["id"] == cursor: break
      recent = cls.cache[index + 1:]
      if recent:
        callback(recent)
        return
    cls.waiters.append(callback)

  def new_messages(self, messages):
    cls = MessageMixin
    logging.info("Sending new message to %r listeners", len(cls.waiters))
    logging.info("online users: %s, sender %s", online_users, self.current_user)
    for callback in cls.waiters:
      try:
        callback(messages)
      except:
        logging.error("Error in waiter callback", exc_info=True)
    cls.waiters = []
    cls.cache.extend(messages)
    if len(cls.cache) > self.cache_size:
      cls.cache = cls.cache[-self.cache_size:]

class MessageNewHandler(BaseHandler, MessageMixin):
  @tornado.web.authenticated
  def post(self):
    message = {
      "id": str(uuid.uuid4()),
      "from": self.current_user,
      "body": self.get_argument("body"),
    }
    message["html"] = self.render_string("message.html", message=message)
    self.write(message)
    self.new_messages([message])

class MessageUpdatesHandler(BaseHandler, MessageMixin):
  @tornado.web.authenticated
  @tornado.web.asynchronous
  def post(self):
    cursor = self.get_argument("cursor", None)
    self.wait_for_messages(self.async_callback(self.on_new_messages),
                 cursor=cursor)

  def on_new_messages(self, messages):
    # Closed client connection
    if self.request.connection.stream.closed():
      online_users.remove(self.current_user)
      return
    self.finish(dict(messages=messages))

class AuthLoginHandler(BaseHandler):
  @tornado.web.asynchronous
  def get(self):
    self.render("login.html")

  def post(self):
    user = self.get_argument("nickname", None)
    if not user:
      self.render("login.html")
    elif user in online_users:
      self.render("login.html", error="昵称已被使用")
    else:
      self.set_secure_cookie("user", user)
      self.redirect(self.get_argument("next", "/"))

class AuthLogoutHandler(BaseHandler):
  def get(self):
    self.clear_cookie("user")
    self.render("logout.html")

def main():
  tornado.options.parse_command_line()
  app = Application()
  http_server = tornado.httpserver.HTTPServer(app, ssl_options={
    "certfile": os.path.expanduser("~/etc/key/server.crt"),
    "keyfile": os.path.expanduser("~/etc/key/server.key"),
  })
  http_server.listen(options.port)
  tornado.ioloop.IOLoop.instance().start()

if __name__ == "__main__":
  main()
