import os
import sys
import json
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


def add_jira_issues(wf, issues):
    for issue in issues:
        title = '{}: {}'.format(issue.key, issue.summary)
        age = 'Updated {}'.format(age_str(issue.updated_age))
        url_base = config.get(ConfigKeys.JIRA_URL)

        if url_base[-1] == '/':
            url_base = url_base[:-1]

        browse_url = url_base + '/browse/' + issue.key

        wf.add_item(
            title,
            age,
            arg=browse_url,
            icon=ICON_WEB,
            valid=True
        )


def my_jira_issues(wf, query=None):
    client = get_jira_client(wf)
    issues = wf.cached_data('my_tix', client.get_users_issues, 60 * 5)

    if query:
        issues = wf.filter(
            query,
            issues,
            key=lambda x: x.key + x.summary
        )

    add_jira_issues(wf, issues)
    wf.send_feedback()


def github_prs(repo, query, wf):
    client = get_github_client(wf)

    get_prs = partial(client.get_prs, repo)
    prs = wf.cached_data(repo.replace('/', '_') + '_prs', get_prs, 60 * 5)

    if query:
        prs = wf.filter(
            query,
            prs,
            key=lambda x: ' '.join([str(x.number), x.username, x.title])
        )

    for pr in prs:
        title = '{}: {}'.format(pr.number, pr.title)
        age = datetime.datetime.now(TIMEZONE) - pr.updated

        subtitle = '[{}] Updated {}'.format(pr.username, age_str(age))

        wf.add_item(
            title,
            subtitle,
            arg=pr.html_url,
            icon=ICON_WEB,
            valid=True
        )

    wf.send_feedback()


def github_emoji(query, wf):
    client = get_github_client(wf)
    emoji_dict = wf.cached_data('github_emoji', client.get_emoji, 60 * 60 * 24)

    emoji = [[k, v] for k, v in emoji_dict.items()]

    if query:
        emoji = wf.filter(query, emoji, key=lambda x: x[0])

    for e in emoji:
        wf.add_item(
            e[0],
            e[1],
            arg=e[1],
            valid=True
        )

    wf.send_feedback()


def github_commits(repo, query, wf):
    client = get_github_client(wf)

    fetch = partial(client.get_commits, repo)

    commits = wf.cached_data(repo.replace('/', '_') + '_commits', fetch, 60 * 5)

    if query:
        commits = wf.filter(
            query,
            commits,
            key=lambda x: ' '.join([str(x.username), x.commit_message])
        )

    for commit in commits:
        age = datetime.datetime.now(TIMEZONE) - commit.date
        subtitle = '[{}] Updated {}'.format(commit.username, age_str(age))

        wf.add_item(
            commit.commit_message,
            subtitle,
            arg=commit.html_url,
            icon=ICON_WEB,
            valid=True
        )

    wf.send_feedback()


def jive_activity(query, wf):
    client = get_jive_client(wf)

    items = wf.cached_data('my_jive_activities', client.get_activity, 60 * 5)

    if query:
        items = wf.filter(
            query,
            items,
            key=lambda x: ' '.join([x.actor_name, x.summary]),
        )

    for item in items:
        if 'liked' in item.verb or 'task' in item.object_type:
            continue

        # age = datetime.datetime.now(TIMEZONE) - item.updated
        subtitle = '[{}:{}] {}: {}'.format(
            item.object_type,
            item.verb,
            item.actor_name,
            item.summary
        )

        wf.add_item(
            item.title,
            subtitle,
            arg=item.url,
            icon=ICON_WEB,
            valid=True
        )

    wf.send_feedback()


def all_hackpads(query, wf):
    client = get_hackpad_client(wf)

    items = wf.cached_data('all_hackpads', client.all_pads, 60 * 5)

    if query:
        items = wf.filter(
            query,
            items,
            key=lambda x: x.title,
        )

    for item in items:
        wf.add_item(
            item.title,
            item.id,
            arg='https://hackpad.com/' + item.id,
            valid=True
        )

    wf.send_feedback()


def trello_me(wf):
    client = get_trello_client(wf)

    return wf.cached_data('trello_me', client.get_me, 60 * 10)


def trello_boards(query, wf):
    client = get_trello_client(wf)

    member_id = config.get(ConfigKeys.TRELLO_MEMBER_ID)

    if not member_id:
        me = trello_me(wf)
        member_id = me.id
        kwargs = {ConfigKeys.TRELLO_MEMBER_ID: member_id}
        config.set(**kwargs)

    fetch = partial(client.get_boards, member_id=member_id)

    boards = wf.cached_data('trello_boards', fetch, 60 * 5)

    if query:
        boards = wf.filter(
            query,
            boards,
            key=lambda x: x.name,
        )

    for board in boards:
        wf.add_item(
            board.name,
            board.id,
            arg=board.short_url,
            valid=True
        )

    wf.send_feedback()


def trello_create_card(query, wf):
    list_id = config.get(ConfigKeys.TRELLO_LIST_ID, enforce=True)

    client = get_trello_client(wf)

    wf.logger.debug('query: {}'.format(query))
    client.create_card(list_id, 'name', 'desc')


def finish_workflow(wf, func):
    if not func:
        raise ValueError('I dunno!')

    result = wf.run(func)
    sys.exit(result)


@click.group()
@click.pass_context
def cli(ctx):
    ctx.obj = {
        'workflow': Workflow(),
    }


@cli.command()
@click.option('--boards', is_flag=True)
@click.option('--createcard', is_flag=True)
@click.option('--query')
@click.pass_context
def trello(ctx, boards, createcard, query):
    wf = ctx.obj['workflow']
    func = None

    if boards:
        func = partial(trello_boards, query)
    elif createcard:
        func = partial(trello_create_card, query)

    finish_workflow(wf, func)


@cli.command()
@click.option('--activity', is_flag=True)
@click.option('--query')
@click.pass_context
def jive(ctx, activity, query):
    wf = ctx.obj['workflow']
    func = None

    if activity:
        func = partial(jive_activity, query)

    finish_workflow(wf, func)


@cli.command()
@click.option('--pads', is_flag=True)
@click.option('--query')
@click.pass_context
def hackpad(ctx, pads, query):
    wf = ctx.obj['workflow']
    func = None

    if pads:
        func = partial(all_hackpads, query)

    finish_workflow(wf, func)


@cli.command()
@click.option('--me', is_flag=True)
@click.option('--query')
@click.pass_context
def jira(ctx, me, query):
    wf = ctx.obj['workflow']

    if me:
        func = lambda x: my_jira_issues(wf, query)
        finish_workflow(wf, func)


@cli.command()
@click.option('--repo')
@click.option('--prs', is_flag=True)
@click.option('--commits', is_flag=True)
@click.option('--emoji', is_flag=True)
@click.option('--query')
@click.pass_context
def github(ctx, repo, prs, commits, emoji, query):
    wf = ctx.obj['workflow']

    func = None

    if prs:
        func = partial(github_prs, repo, query)
    elif commits:
        func = partial(github_commits, repo, query)
    elif emoji:
        func = partial(github_emoji, query)

    if not func:
        raise ValueError('I dunno!')

    finish_workflow(wf, func)


if __name__ == '__main__':
    cli()
