VENV := .venv/bin

.PHONY: setup test update universe screen app notify clean

setup:            ## Pasang virtualenv dan dependensi
	python3 -m venv .venv
	$(VENV)/pip install -q --upgrade pip
	$(VENV)/pip install -q -e .
	$(VENV)/pip install -q -r requirements.txt

test:             ## Jalankan test (tanpa jaringan)
	$(VENV)/python -m pytest

update:           ## Segarkan cache harga dan fundamental
	$(VENV)/idxscreen update

universe:         ## Perbarui daftar emiten dari screener Yahoo
	$(VENV)/idxscreen fetch-universe

screen:           ## Contoh screening
	$(VENV)/idxscreen screen --preset value --funnel

app:              ## Jalankan antarmuka web
	$(VENV)/streamlit run app.py

notify:           ## Uji pesan WhatsApp harian tanpa mengirim
	$(VENV)/idxscreen notify --preset lonjakan --dry-run

clean:            ## Hapus cache dan berkas sementara
	rm -rf .cache out .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
