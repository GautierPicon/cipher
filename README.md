# file-cipher

CLI file encryption tool based on **AES-256-GCM** and **PBKDF2-SHA256**.

## Dependencies

- [`cryptography`](https://cryptography.io) — cryptographic primitives
- [`typer`](https://typer.tiangolo.com) — CLI interface
- [`rich`](https://rich.readthedocs.io) — terminal display

## Installation

```bash
# Clone / create the project
cd file-cipher

# Install dependencies and create environment with uv
uv sync

# Run via uv run
uv run cipher --help
```

## Commands reference

### encrypt
```bash
cipher encrypt <file>
cipher encrypt <file> -o <output>
cipher encrypt <file> --overwrite
cipher encrypt <file> -o <output> --overwrite
```

### decrypt
```bash
cipher decrypt <file.enc>
cipher decrypt <file.enc> -o <output>
cipher decrypt <file.enc> --overwrite
cipher decrypt <file.enc> -o <output> --overwrite
```

### info
```bash
cipher info <file.enc>
```

### help
```bash
cipher --help
cipher encrypt --help
cipher decrypt --help
cipher info --help
```

## Usage

### Encrypt a file
```bash
uv run cipher encrypt secret.txt
# → creates secret.txt.enc

uv run cipher encrypt rapport.pdf -o vault.enc
```

### Decrypt a file
```bash
uv run cipher decrypt secret.txt.enc
# → recreates secret.txt

uv run cipher decrypt vault.enc -o restored_report.pdf
```

### Inspect an encrypted file (without decrypting)
```bash
uv run cipher info secret.txt.enc
```

## `.enc` file format

```
┌──────────────────────────────────────────────────┐
│ MAGIC     (8 bytes)   "CIPHER01"                │
│ ITERATIONS(4 bytes)   PBKDF2 iteration count    │
│ SALT      (32 bytes)  random salt               │
│ NONCE     (12 bytes)  AES-GCM nonce             │
│ CIPHERTEXT + TAG GCM  (rest of file)            │
└──────────────────────────────────────────────────┘
```

## Security

| Component | Choice | Why |
|-----------|--------|-----|
| Encryption | AES-256-GCM | Authenticated (integrity + confidentiality) |
| KDF | PBKDF2-SHA256 | NIST standard, slows brute-force |
| Iterations | 480,000 | NIST 2023 recommendation |
| Salt | 32 random bytes | Protects against rainbow tables |
| Nonce | 12 random bytes | 96 bits = GCM standard |
