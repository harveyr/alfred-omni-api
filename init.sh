#!/bin/sh

if ! [ -d "./bin" ]; then
    virtualenv .
fi

source bin/activate

pip install click
pip install -U git+git://github.com/harveyr/omni-api.git
