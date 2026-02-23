#include <stdio.h>
#include <string.h>
#include <stdlib.h>

char *gets(char *s) {
    int c;
    char *p = s;
    while ((c = getchar()) != EOF && c != '\n') {
        *p++ = (char)c;
    }
    *p = '\0';
    return s;
}

void win() {
    char flag[256];
    FILE *f = fopen("flag.txt", "r");
    if (!f) {
        puts("flag missing");
        return;
    }
    if (fgets(flag, sizeof(flag)-1, f)) {
        printf("FLAG: %s\n", flag);
    } else {
        puts("couldn't read flag");
    }
    fclose(f);
}

void vuln() {
    char buf[64];
    puts("Tell me something:");
    gets(buf);
    puts("Thanks!");
}

int main() {
    setvbuf(stdout, NULL, _IONBF, 0);
    vuln();
    return 0;
}
