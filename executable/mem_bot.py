from bot_settings import *
import vk_api
import telebot
import os
import wget
import psycopg2


class MemyProKotovBot:
    def __init__(self):
        self.vk_session = vk_api.VkApi(VK_LOGIN, VK_PASSWORD)
        self.vk_session.auth()       
        self.vk = self.vk_session.get_api()

        self._db_conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        self._db_cursor = self._db_conn.cursor()
        
        self.bot = telebot.TeleBot(TOKEN)
        self._add_handlers()

    def _parse_response(self, response):
        """
        Return result in the format: [text_msg, attachment1, attachment2, ...]
        """
        result = []
        
        for item in response['items']:
            if "is_pinned" in item.keys():
                continue
            temp = []
            if not item['text']:
                temp.append("")
            else:
                temp.append(item['text'])
            
            #if item['attachments']:
            if 'attachments' in item.keys():
                for attachment in item['attachments']:
                    if attachment['type'] == 'photo':
                        temp.append(attachment['photo']['photo_604'])
            result.append(temp)
        result.reverse()
        return result
    
    def _get_last_post(self, api_response):
        if len(api_response['items']) == 1:
            if 'is_pinned' in api_response['items'][0].keys():
                api_response = self.vk.wall.get(domain=PUBLIC_DOMEN, count=2)

        first_post = api_response['items'][0]
        second_post = api_response['items'][1]

        if 'is_pinned' in first_post.keys():
            return second_post['id']
        return first_post['id']

    def _get_last_post_db(self, user):
        self._db_cursor.execute("""SELECT last_post FROM users WHERE user_id = """ + str(user.id))
        res = self._db_cursor.fetchall()

        return res[0][0]

    def _set_last_post_db(self, last_post, user):
        self._db_cursor.execute("""UPDATE users SET last_post = {0} WHERE user_id = {1}""".format(last_post, user.id))

        self._db_conn.commit()

    def _send_retrieved_posts(self, posts, chat):
        for r in posts:
            text = r[0]
            if len(r) > 1:
                try:
                    if len(r) == 2:
                        # self.bot.send_photo(message.chat.id, r[1], caption=text)
                        if len(text) < 200:
                            self.bot.send_photo(chat.id, r[1], caption=text)
                        else:
                            self.bot.send_photo(chat.id, r[1])
                            self.bot.send_message(chat.id, text)
                    elif len(r) > 2:
                        media = [telebot.types.InputMediaPhoto(m) for m in r[1:]]
                        self.bot.send_media_group(chat.id, media)
                        if text:
                            self.bot.send_message(chat.id, text)
            
                except Exception as exc:
                    #print("Request exception occured, but I`m still alive (" + str(exc) + ")")
                    if "group send failed" in str(exc):
                        print("Group send failed. Trying to load pictures manualy")
                        downloaded = []
                        for address in r[1:]:
                            downloaded.append(wget.download(address))
                        print("All pictures downloaded")

                        self.bot.send_media_group(chat.id, [telebot.types.InputMediaPhoto(open(d, 'rb')) for d in downloaded])
                        print("Done.")
                        for d in downloaded:
                            os.remove(d)
                        print("temporary files heve been removed")
            else:
                if text:
                    self.bot.send_message(chat.id, text)

    def send_posts(self, message, count):
        response = self.vk.wall.get(domain=PUBLIC_DOMEN, count=count)
        result = self._parse_response(response)
        self._send_retrieved_posts(result, message.chat)
        
        
    def _user_registered(self, user):
        self._db_cursor.execute("""SELECT * from users WHERE user_id = """ + str(user.id))

        rows = self._db_cursor.fetchall()
        if len(rows) == 0:
            return False
        return True
    def _register_user(self, user_id, last_post_id):
        self._db_cursor.execute("INSERT INTO users VALUES({0}, {1})".format(str(user_id), str(last_post_id)))
        self._db_conn.commit()

    def _retrieve_posts(self, last_post):
        new_last_post = 0
        offset = 0
        result = []
        while True:
            response = self.vk.wall.get(domain=PUBLIC_DOMEN, count=1, offset = offset)
            if 'is_pinned' in response['items'][0].keys():
                offset += 1
                continue
            if response['items'][0]['id'] == last_post:
                break
            offset += 1

        if offset == 0:
            return result

        response = self.vk.wall.get(domain=PUBLIC_DOMEN, count=offset)
        new_last_post = self._get_last_post(response)
        result = self._parse_response(response)

        return result, new_last_post

    def _add_handlers(self):
        @self.bot.message_handler(commands=['start'])
        def start_work(message):
            #self.send_posts(message, 5)
            if self._user_registered(message.from_user):
                #Get last post id and retrieve all post until this value
                last_post = self._get_last_post_db(message.from_user)
                self.bot.send_message(message.chat.id, "You have been already registered. Your last post is " + str(last_post))
            else:
                #Retrieve last 10 posts and add a user to DB with last post id
                response = self.vk.wall.get(domain=PUBLIC_DOMEN, count=10)
                last_post = self._get_last_post(response)
                result = self._parse_response(response)
                self._send_retrieved_posts(result, message.chat)

                self._register_user(message.from_user.id, last_post)

                self.bot.send_message(message.chat.id, "You are now registered with id " + str(message.from_user.id) + " and last post " + str(last_post))


        @self.bot.message_handler(commands=['update'])
        def update_work(message):
            last_post = self._get_last_post_db(message.from_user)
            result, last_post = self._retrieve_posts(last_post)
            if len(result) == 0:
                self.bot.send_message(message.chat.id, "Новых мемесов нет")
            else: 
                self._send_retrieved_posts(result, message.chat)
                self._set_last_post_db(last_post, message.from_user)


        
    def updates_listener_start(self):
        self.bot.polling()
