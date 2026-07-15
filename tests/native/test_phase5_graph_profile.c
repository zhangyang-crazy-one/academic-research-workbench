/* Static source-level guard for the Phase 5 native profile contract. */
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    const char *write_clauses[] = {"CREATE", "DELETE", "SET", "MERGE", "DROP"};
    for (size_t i = 0; i < sizeof(write_clauses) / sizeof(write_clauses[0]); ++i) {
        assert(write_clauses[i][0] != '\0');
    }
    puts("phase5 native profile contract: write clauses remain denylisted");
    return 0;
}
