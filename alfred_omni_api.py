import os
import sys
import json
import time
import datetime
from functools import partial

from omni_api.hackpad import HackpadClient
from omni_api.jira import JiraClient
from omni_api.jive import JiveClient
from omni_api.github import GithubClient
from omni_api.trello import TrelloClient

import click
import pytz
from workflow import Workflow, ICON_WEB

TIMEZONE = pytz.timezone('US/Pacific')


class AuthKeys(object):
    HACKPAD_CLIENT_ID = 'omniapi_hackpad_client_id'
    HACKPAD_SECRET = 'omniapi_hackpad_secret'
    JIRA_USERNAME = 'omniapi_jira_user'
    JIRA_PASSWORD = 'omniapi_jira_pw'
    JIVE_USERNAME = 'omniapi_jive_user'
    JIVE_PASSWORD = 'omniapi_jive_pw'
    GITHUB_TOKEN = 'omniapi_github_token'
    TRELLO_API_KEY = 'omniapi_trello_api_key'
    TRELLO_TOKEN = 'omniapi_trello_token'


class ConfigKeys(object):
    JIVE_URL = 'jive_url'
    JIRA_URL = 'jira_url'
    TRELLO_MEMBER_ID = 'trello_member_id'
    TRELLO_BOARD_ID = 'trello_board_id'
    TRELLO_LIST_ID = 'trello_list_id'


class Config(object):
    def __init__(self):
        base_path = os.path.split(os.path.realpath(__file__))[0]
        self.config_file = os.path.join(base_path, 'config_save')

        if not os.path.exists(self.config_file):
            self.init_config()
        else:
            try:
                self.load_config()
            except ValueError:
                self.init_config()

    def init_config(self):
        self.set_config({})

    def set_config(self, dict_):
        with open(self.config_file, 'w') as f:
            json.dump(dict_, f)

    def load_config(self):
        with open(self.config_file, 'r') as f:
            return json.load(f)

    def set(self, **kwargs):
        data = self.load_config()
        data.update(**kwargs)

        self.set_config(data)

    def get(self, key, enforce=True):
        data = self.load_config()

        value = data.get(key)

        if enforce and not value:
            raise ValueError(
                'No value found for "{}". Try running config.py'.format(key)
            )

        return value


config = Config()


class ListHandler(object):
    """
    The new way of fetching and displaying lists. Converting over to this.
    """

    def __init__(
        self,
        query='',
        cache_timeout=60 * 10
    ):
        self.workflow = Workflow()
        self.query = query
        self.cache_timeout = cache_timeout

    @property
    def cache_key(self):
        return self.__class__.__name__

    def run(self):
        result = self.workflow.run(self._run)
        self.workflow.send_feedback()
        sys.exit(result)

    def fetch(self):
        raise NotImplementedError

    def _run(self, workflow):
        items = workflow.cached_data(
            self.cache_key,
            self.fetch,
            self.cache_timeout
        )

        if self.query:
            items = self.filtered_items(items, self.query)

        for item in items:
            self.add_item(item)

    def add_item(self, item):
        raise NotImplementedError

    def filtered_items(self, items, query):
        return self.workflow.filter(
            query,
            items,
            key=lambda x: str(x)
        )


def throttled(func):
    def inner(*args, **kwargs):
        key = 'called_{}'.format(func.__name__)
        val = config.get(key)

        time.sleep(1)

        if val and config.get(key) != val:
            return None

        config.set(**{key: time.time()})

        return func(*args, **kwargs)

    return inner


def age_str(delta):
    total_seconds = int(delta.total_seconds())

    if delta.days > 365:
        age = float(delta.days) / 365
        unit = 'year'
    elif delta.days > 30:
        age = delta.days / 30
        unit = 'month'
    elif delta.days > 1:
        age = delta.days
        unit = 'day'
    elif total_seconds > 3600:
        age = total_seconds / 3600
        unit = 'hour'
    elif total_seconds > 60:
        age = total_seconds / 60
        unit = 'minute'
    else:
        return 'just now'

    if age > 1:
        unit += 's'

    if isinstance(age, float):
        age = '{:.1f}'.format(age)

    return '{} {} ago'.format(age, unit)


def get_jira_client(wf):
    return JiraClient(
        config.get(ConfigKeys.JIRA_URL),
        wf.get_password(AuthKeys.JIRA_USERNAME),
        wf.get_password(AuthKeys.JIRA_PASSWORD)
    )


def get_github_client(wf):
    return GithubClient(wf.get_password(AuthKeys.GITHUB_TOKEN))


def get_jive_client(wf):
    return JiveClient(
        config.get(ConfigKeys.JIVE_URL),
        wf.get_password(AuthKeys.JIVE_USERNAME),
        wf.get_password(AuthKeys.JIVE_PASSWORD)
    )


def get_hackpad_client(wf):
    return HackpadClient(
        wf.get_password(AuthKeys.HACKPAD_CLIENT_ID),
        wf.get_password(AuthKeys.HACKPAD_SECRET)
    )


def get_trello_client(wf):
    return TrelloClient(
        wf.get_password(AuthKeys.TRELLO_API_KEY),
        wf.get_password(AuthKeys.TRELLO_TOKEN)
    )


class JiraIssuesBaseHandler(ListHandler):
    def add_item(self, item):
        title = '{}: {}'.format(item.key, item.summary)
        age = 'Updated {}'.format(age_str(item.updated_age))
        url_base = config.get(ConfigKeys.JIRA_URL)

        if url_base[-1] == '/':
            url_base = url_base[:-1]

        browse_url = url_base + '/browse/' + item.key

        self.workflow.add_item(
            title,
            age,
            arg=browse_url,
            icon=ICON_WEB,
            valid=True
        )

    def filtered_items(self, items, query):
        return self.workflow.filter(
            query,
            items,
            key=lambda x: x.key + x.summary
        )


class JiraMyIssuesHandler(JiraIssuesBaseHandler):
    def fetch(self):
        client = get_jira_client(self.workflow)

        return client.get_users_issues()


class GithubRepoBaseHandler(ListHandler):
    """
    Handles Github lists that require a specific repo.
    """

    def __init__(self, repo, *args, **kwargs):
        super(GithubRepoBaseHandler, self).__init__(*args, **kwargs)

        if not repo:
            raise ValueError('A repo is required. Got {}'.format(repo))

        self.repo = repo
        self.client = get_github_client(self.workflow)

    @property
    def cache_key(self):
        return '_'.join([self.__class__.__name__] + self.repo.split('/'))


class GithubPrsHandler(GithubRepoBaseHandler):

    def fetch(self):
        return self.client.get_prs(self.repo)

    def filtered_items(self, items, query):
        return self.workflow.filter(
            query,
            items,
            key=lambda x: ' '.join([str(x.number), x.username, x.title])
        )

    def add_item(self, item):
        title = '{}: {}'.format(item.number, item.title)
        age = datetime.datetime.now(TIMEZONE) - item.updated

        subtitle = '[{}] Updated {}'.format(item.username, age_str(age))

        self.workflow.add_item(
            title,
            subtitle,
            arg=item.html_url,
            icon=ICON_WEB,
            valid=True
        )


class GithubCommitsHandler(GithubRepoBaseHandler):

    def fetch(self):
        return self.client.get_commits(self.repo)

    def add_item(self, item):
        age = datetime.datetime.now(TIMEZONE) - item.date
        subtitle = '[{}] Updated {}'.format(item.username, age_str(age))

        self.workflow.add_item(
            item.commit_message,
            subtitle,
            arg=item.html_url,
            icon=ICON_WEB,
            valid=True
        )

    def filtered_items(self, items, query):
        return self.workflow.filter(
            query,
            items,
            key=lambda x: ' '.join([str(x.username), x.commit_message])
        )


class GithubEmojiHandler(ListHandler):
    def fetch(self):
        client = get_github_client(self.workflow)
        result = client.get_emoji()

        emoji_list = [[k, v] for k, v in result.items()]

        return emoji_list

    def add_item(self, item):
        self.workflow.add_item(
            item[0],
            item[1],
            arg=item[1],
            valid=True
        )

    def filtered_items(self, items, query):
        return self.workflow.filter(
            query,
            items,
            key=lambda x: x[0]
        )


class MyJiveActivityHandler(ListHandler):
    def fetch(self):
        client = get_jive_client(self.workflow)

        return client.get_activity()

    def filtered_items(self, items, query):
        return self.workflow.filter(
            query,
            items,
            key=lambda x: ' '.join([x.actor_name, x.summary]),
        )

    def add_item(self, item):
        if 'liked' in item.verb or 'task' in item.object_type:
            return

        subtitle = '[{}:{}] {}: {}'.format(
            item.object_type,
            item.verb,
            item.actor_name,
            item.summary
        )

        self.workflow.add_item(
            item.title,
            subtitle,
            arg=item.url,
            icon=ICON_WEB,
            valid=True
        )


class HackpadsHandler(ListHandler):
    def fetch(self):
        client = get_hackpad_client(self.workflow)

        return client.all_pads()

    def filtered_items(self, items, query):
        return self.workflow.filter(
            query,
            items,
            key=lambda x: x.title,
        )

    def add_item(self, item):
        self.workflow.add_item(
            item.title,
            item.id,
            arg='https://hackpad.com/' + item.id,
            valid=True
        )


def trello_me(wf):
    client = get_trello_client(wf)

    return wf.cached_data('trello_me', client.get_me, 60 * 10)


class TrelloBaseHandler(ListHandler):
    @property
    def client(self):
        return TrelloClient(
            self.workflow.get_password(AuthKeys.TRELLO_API_KEY),
            self.workflow.get_password(AuthKeys.TRELLO_TOKEN)
        )

    def fetch_me(self):
        return self.workflow.cached_data(
            'trello_me',
            self.client.get_me,
            60 * 60
        )

    def fetch_my_member_id(self):
        member_id = config.get(ConfigKeys.TRELLO_MEMBER_ID)

        if not member_id:
            me = self.fetch_me()
            member_id = me.id
            config.set(**{ConfigKeys.TRELLO_MEMBER_ID: member_id})

        return member_id


class TrelloBoardsHandler(TrelloBaseHandler):

    def fetch(self):
        member_id = self.fetch_my_member_id()

        if not member_id:
            raise ValueError('Bad member id: {}'.format(member_id))

        return self.client.get_boards(member_id)

    def filtered_items(self, items, query):
        return self.workflow.filter(
            query,
            items,
            key=lambda x: x.name,
        )

    def add_item(self, item):
        self.workflow.add_item(
            item.name,
            item.id,
            arg=item.short_url,
            valid=True
        )


def trello_create_card(query, wf):
    list_id = config.get(ConfigKeys.TRELLO_LIST_ID, enforce=True)
    client = get_trello_client(wf)
    client.create_card(list_id, query)


def run_workflow(func):
    result = Workflow().run(func)
    sys.exit(result)


@click.group()
def cli():
    pass


@cli.command()
@click.option('--boards', is_flag=True)
@click.option('--createcard', is_flag=True)
@click.option('--query')
def trello(boards, createcard, query):
    if boards:
        TrelloBoardsHandler().run()
    elif createcard:
        run_workflow(partial(trello_create_card, query))


@cli.command()
@click.option('--activity', is_flag=True)
@click.option('--query')
def jive(activity, query):

    if activity:
        MyJiveActivityHandler(
            query,
            cache_timeout=60 * 5
        ).run()


@cli.command()
@click.option('--pads', is_flag=True)
@click.option('--query')
def hackpad(pads, query):
    if pads:
        HackpadsHandler(query=query).run()


@cli.command()
@click.option('--me', is_flag=True)
@click.option('--query')
def jira(me, query):
    if me:
        JiraMyIssuesHandler(query=query).run()


@cli.command()
@click.option('--repo')
@click.option('--prs', is_flag=True)
@click.option('--commits', is_flag=True)
@click.option('--emoji', is_flag=True)
@click.option('--query')
def github(repo, prs, commits, emoji, query):
    if prs:
        GithubPrsHandler(repo, query=query).run()
    elif commits:
        GithubCommitsHandler(repo, query=query).run()
    elif emoji:
        GithubEmojiHandler(
            query=query,
            cache_timeout=60 * 60 * 24
        ).run()
    else:
        raise ValueError('I dunno!')

if __name__ == '__main__':
    cli()
