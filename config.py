import click
import workflow

from alfred_omni_api import AuthKeys, ConfigKeys, config
from omni_api.trello import TrelloClient


wf = workflow.Workflow()


def get_password(key):
    try:
        return wf.get_password(key)
    except workflow.PasswordNotFound:
        return None


def prompt_for_keychain(label, key, hide=True):
    value = get_password(key)

    if not value or click.confirm('Reset {}'.format(label)):
        value = click.prompt('{}'.format(label), hide_input=hide)
        wf.save_password(key, value)


def prompt_for_config(label, key):
    current = config.get(key, enforce=False)

    value = click.prompt(label, default=current)
    kwargs = {key: value}
    config.set(**kwargs)

    assert config.get(key) == value


@click.group()
def cli():
    pass


@cli.command()
def jira():
    prompt_for_config('JIRA URL', ConfigKeys.JIRA_URL)
    prompt_for_keychain('JIRA username', AuthKeys.JIRA_USERNAME, hide=False)
    prompt_for_keychain('JIRA password', AuthKeys.JIRA_PASSWORD)


@cli.command()
def github():
    prompt_for_keychain('Github token', AuthKeys.GITHUB_TOKEN)


@cli.command()
def jive():
    prompt_for_config('Jive URL', ConfigKeys.JIVE_URL)
    prompt_for_keychain('Jive username', AuthKeys.JIVE_USERNAME, hide=False)
    prompt_for_keychain('Jive password', AuthKeys.JIVE_PASSWORD)


@cli.command()
def trello():
    prompt_for_keychain('Trello API key', AuthKeys.TRELLO_API_KEY, hide=False)
    prompt_for_keychain('Trello token', AuthKeys.TRELLO_TOKEN)

    client = TrelloClient(
        wf.get_password(AuthKeys.TRELLO_API_KEY),
        wf.get_password(AuthKeys.TRELLO_TOKEN)
    )

    me = client.get_me()
    boards = client.get_boards(me.id)

    click.secho('Boards', bold=True)

    for i, board in enumerate(boards):
        click.echo('{}: {}'.format(i, board.name))

    board_index = click.prompt('Choose a board for card creation', type=int)
    board = boards[board_index]

    lists = client.get_lists(board.id)

    for i, list_ in enumerate(lists):
        click.echo('{}: {}'.format(i, list_.name))

    list_index = click.prompt('Choose a list for card creation', type=int)
    list_ = lists[list_index]

    kwargs = {
        ConfigKeys.TRELLO_MEMBER_ID: me.id,
        ConfigKeys.TRELLO_BOARD_ID: board.id,
        ConfigKeys.TRELLO_LIST_ID: list_.id,
    }

    config.set(**kwargs)


@cli.command()
def hackpad():
    url = 'https://hackpad.com/ep/account/settings/'
    if click.confirm(
        'Hackpad creds can be found at {}. Launch?'.format(url)
    ):
        click.launch(url)

    prompt_for_keychain('HackPad client id', AuthKeys.HACKPAD_CLIENT_ID)
    prompt_for_keychain('HackPad secret', AuthKeys.HACKPAD_SECRET)


if __name__ == '__main__':
    cli()
