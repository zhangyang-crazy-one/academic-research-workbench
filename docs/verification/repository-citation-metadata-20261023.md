# Root citation metadata repair

The root `CITATION.cff` requested in #37 was absent; the vendored ARS citation
file describes upstream ARS and cannot substitute for ARW's identity. The new
root file identifies the project and its contributor collective without
inventing a personal name, ORCID, DOI or publication date.

## 已验证

- `uvx --from cffconvert cffconvert -i CITATION.cff --validate` passed against
  CFF schema 1.2.0.
- Independently parsed CFF, CodeMeta and pyproject agree on project title,
  repository and version 0.2.1.
- `license-url` points to the existing component-scoped root license index.
  No blanket or dual-license grant is inferred from the separate CC-BY-NC and
  MIT component entries in CodeMeta.
- `git diff --check` passed.

## 未验证

GitHub's rendered citation UI and external repository/DOI registration. The
version describes the current candidate source; it is not a release claim.
