env:
	python3 -m venv env
	. env/bin/activate
	env/bin/pip install --upgrade pip
	env/bin/pip install --upgrade -r requirements.py3.txt
	cp -rp env env.vanilla

dev: env
	env/bin/pip install --editable .
	env/bin/pip install --upgrade -r requirements-dev.txt
	env/bin/pip install --upgrade -r requirements-test.txt

prod: env
	env/bin/pip install .
	env/bin/pip install --upgrade -r requirements-prod.txt

clean:
	rm -rf env
	rm -rf env.vanilla

test: dev
	env/bin/py.test
	#env/bin/py.test --lf

serve: dev
	# In the first shell, run a copy of remarkbox using:
	env/bin/pserve development.ini --reload

http: dev
	# In the second shell, run a "mock" simple HTTP webserver to serve index.html:
	env/bin/python -m http.server 8000
