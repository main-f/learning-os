import json
from .importer import import_topics

if __name__ == "__main__":
    print(json.dumps(import_topics(),ensure_ascii=False,indent=2))
