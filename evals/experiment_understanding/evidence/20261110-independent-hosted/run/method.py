
import itertools, json, os, pathlib, socket, sys
assert os.getcwd() == '/work'
assert not os.environ.get('ANSWER_CANARY')
for path in ['/home/runner/work/academic-research-workbench/academic-research-workbench/build/evidence/ci-independent-pilot/test_actual_namespace_blocks_a0/hidden-reference.json', '/home/runner/work/academic-research-workbench/academic-research-workbench/build/evidence/ci-independent-pilot/test_actual_namespace_blocks_a0/resume.json', '/home/runner/work/academic-research-workbench/academic-research-workbench/build/evidence/ci-independent-pilot/test_actual_namespace_blocks_a0/stdout.log', '/home/runner/work/academic-research-workbench/academic-research-workbench/evals/experiment_understanding/v1/hidden-reference.json']:
    assert not pathlib.Path(path).exists(), path
assert not pathlib.Path('/work/resume.json').exists()
s = socket.socket()
s.settimeout(0.1)
assert s.connect_ex(('1.1.1.1', 443)) != 0
pathlib.Path('/work/resume.json').write_text('private prior attempt')
with open(sys.argv[1]) as stream:
    public = json.load(stream)
mean = sum(row['value'] for row in public['observations']) / len(public['observations'])
print(json.dumps({
    'selected_config': '0000',
    'responses': [{'config': ''.join(bits), 'value': mean}
                  for bits in itertools.product('01', repeat=4)],
}))
