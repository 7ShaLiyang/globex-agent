import asyncio,json
from pathlib import Path
from app.composition import Container
async def main():
    c=Container();await c.start();scores=[]
    try:
        for case in json.loads(Path('eval/search_cases.json').read_text()):
            result=await c.search.search(case['query'],3)
            ids={p['id'] for p in result['products']}; relevant=set(case['relevant'])
            recall=len(ids & relevant)/len(relevant);scores.append(recall)
            print(f"{case['query']}: recall@3={recall:.2f} [{result['mode']}]")
        print(f'Macro recall@3={sum(scores)/len(scores):.3f}')
    finally: await c.close()
if __name__=='__main__': asyncio.run(main())
