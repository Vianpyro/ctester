/* A stand-in for Unity, wide enough for the sandbox checks and nothing more.
 *
 * The engine has to prove its own invariants on a bare clone, but `shared/unity` belongs
 * to a content root and only one root may hold it: vendoring a second copy of the real
 * framework here would duplicate the very thing that rule protects. grade.rs is bound to
 * real Unity's output by its own Rust tests, and it reads exactly two lines -- the
 * "N Tests M Failures K Ignored" summary and "<file>:<line>:<name>:FAIL". This speaks both.
 */
#ifndef UNITY_H
#define UNITY_H

void setUp(void);
void tearDown(void);

void unity_begin(const char *file);
int unity_end(void);
void unity_run(void (*test)(void), const char *name, int line);
void unity_note_failure(int line);
int unity_streq(const char *expected, const char *actual);
int unity_within(double delta, double expected, double actual);

#define UNITY_BEGIN() unity_begin(__FILE__)
#define UNITY_END() unity_end()
#define RUN_TEST(fn) unity_run(fn, #fn, __LINE__)

/* A failing assertion ends the test, as Unity's longjmp does. */
#define UNITY_FAIL_HERE() do { unity_note_failure(__LINE__); return; } while (0)

#define TEST_ASSERT_TRUE(cond) do { if (!(cond)) UNITY_FAIL_HERE(); } while (0)
#define TEST_ASSERT_FALSE(cond) do { if ((cond)) UNITY_FAIL_HERE(); } while (0)
#define TEST_ASSERT_NULL(ptr) TEST_ASSERT_TRUE((ptr) == 0)
#define TEST_ASSERT_NOT_NULL(ptr) TEST_ASSERT_TRUE((ptr) != 0)
#define TEST_ASSERT_EQUAL_INT(expected, actual) \
    do { if ((long long)(expected) != (long long)(actual)) UNITY_FAIL_HERE(); } while (0)
#define TEST_ASSERT_EQUAL(expected, actual) TEST_ASSERT_EQUAL_INT((expected), (actual))
#define TEST_ASSERT_EQUAL_STRING(expected, actual) \
    do { if (!unity_streq((expected), (actual))) UNITY_FAIL_HERE(); } while (0)
#define TEST_ASSERT_DOUBLE_WITHIN(delta, expected, actual) \
    do { if (!unity_within((delta), (expected), (actual))) UNITY_FAIL_HERE(); } while (0)
#define TEST_ASSERT_FLOAT_WITHIN(delta, expected, actual) \
    TEST_ASSERT_DOUBLE_WITHIN((delta), (expected), (actual))

#endif /* UNITY_H */
