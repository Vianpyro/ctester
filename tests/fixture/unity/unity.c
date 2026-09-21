#include "unity.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

static const char *unity_file = "";
static int unity_total;
static int unity_failures;
static int unity_failed_line;

void unity_begin(const char *file)
{
    unity_file = file;
    unity_total = 0;
    unity_failures = 0;
}

void unity_note_failure(int line)
{
    unity_failed_line = line;
}

void unity_run(void (*test)(void), const char *name, int line)
{
    unity_failed_line = 0;
    unity_total++;
    setUp();
    test();
    tearDown();
    if (unity_failed_line) {
        unity_failures++;
        printf("%s:%d:%s:FAIL\n", unity_file, unity_failed_line, name);
    } else {
        printf("%s:%d:%s:PASS\n", unity_file, line, name);
    }
}

int unity_end(void)
{
    printf("\n-----------------------\n");
    printf("%d Tests %d Failures 0 Ignored\n", unity_total, unity_failures);
    printf("%s\n", unity_failures ? "FAIL" : "OK");
    return unity_failures;
}

int unity_streq(const char *expected, const char *actual)
{
    if (expected == 0 || actual == 0) {
        return expected == actual;
    }
    return strcmp(expected, actual) == 0;
}

int unity_within(double delta, double expected, double actual)
{
    return fabs(expected - actual) <= fabs(delta);
}
