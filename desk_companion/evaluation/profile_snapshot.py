"""Selected model policies for isolated workers; never copy account credentials."""
import json
from contextlib import closing
import sqlite3


def selected_policies(items):
    from desk_companion.models import model_capacity,model_generation
    from desk_companion.infrastructure.state import model_price_snapshot
    capacities={};prices={};bindings={}
    for item in items:
        capacities[item['id']]=model_capacity.load(item['id'])
        value=model_price_snapshot(item['model'])
        if value is not None:prices[item['model']]=value
        value=model_generation.binding(item['id'],item['model'],item['base_url'].rstrip('/')+'/chat/completions')
        if value is not None:bindings[item['id']]=value
    return dict(capacities=capacities,prices=prices,bindings=bindings)


def write_policies(profile,snapshot):
    (profile/'model-capacity.json').write_text(json.dumps(snapshot['capacities'],ensure_ascii=False),'utf-8')
    if snapshot['bindings']:
        path=profile/'memory/model_generation.sqlite3';path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(path))as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS bindings(model TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.executemany('INSERT INTO bindings VALUES(?,?)',[(key,json.dumps(value))for key,value in snapshot['bindings'].items()])
