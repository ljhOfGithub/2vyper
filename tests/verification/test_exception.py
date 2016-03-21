from py2viper_contracts.contracts import *


class MyException(Exception):
    pass


class MySpecialException(MyException):
    pass


class MyOtherException(Exception):
    pass


class ParameterizedException(Exception):
    def __init__(self, num: int) -> None:
        Ensures(Acc(self.num))  # type: ignore
        Ensures(self.num == num)  # type: ignore
        self.num = num


class Container:
    def __init__(self) -> None:
        Ensures(Acc(self.value))  # type: ignore
        self.value = 0


def raised_and_declared(input: int, incon: Container) -> Container:
    Requires(incon != None and Acc(incon.value))
    Ensures(Acc(incon.value) and (
        Result() != None and (Acc(Result().value) and Result().value == input)))
    Exsures(MyException, Acc(incon.value) and incon.value == -1)
    res = Container()
    incon.value = -1
    if input == 22:
        raise MyException()
    res.value = input
    return res


def raised_and_declared_2(input: int, incon: Container) -> Container:
    Requires(incon != None and Acc(incon.value))
    Ensures(Acc(incon.value) and (
        Result() != None and (Acc(Result().value) and Result().value == input)))
    Exsures(Exception, Acc(incon.value) and incon.value == -1)
    res = Container()
    incon.value = -1
    if input == 22:
        raise MyException()
    res.value = input
    return res


def raised_and_declared_3(input: int, incon: Container) -> None:
    Requires(incon != None and Acc(incon.value))
    Ensures(False)
    Exsures(MyException, Acc(incon.value) and incon.value == -2)
    incon.value = -2
    raise MyException()


def raised_and_declared_4(input: int, incon: Container) -> None:
    Requires(incon != None and Acc(incon.value))
    Ensures(False)
    #:: ExpectedOutput(postcondition.violated:assertion.false)
    Exsures(MyException, Acc(incon.value) and incon.value == -3)
    incon.value = -2
    raise MyException()


def raised_and_declared_5(input: int, incon: Container) -> None:
    Requires(incon != None and Acc(incon.value))
    Ensures(False)
    Exsures(MyException, Acc(incon.value) and incon.value == -3)
    Exsures(MyOtherException, True)
    incon.value = -3
    raise MyException()


def raised_and_undeclared(input: int, incon: Container) -> Container:
    Requires(incon != None and Acc(incon.value))
    Ensures(Acc(incon.value) and (
        Result() != None and (Acc(Result().value) and Result().value == input)))
    res = Container()
    incon.value = -1
    if input == 22:
        #:: ExpectedOutput(exhale.failed:assertion.false)
        raise MyException()
    res.value = input
    return res

def raised_and_declared_6(input: int, incon: Container) -> None:
    Requires(incon != None and Acc(incon.value))
    Ensures(False)
    Exsures(MyException, Acc(incon.value) and incon.value == -3)
    Exsures(MyOtherException, True)
    if input > 2:
        incon.value = -3
        raise MyException()
    else:
        raise MyOtherException()

def helper(out: Container, i: int) -> None:
    Requires(Acc(out.value))
    Ensures(Acc(out.value) and out.value == 12)
    Exsures(MyException, Acc(out.value) and out.value == 13)
    if i > 34:
        out.value = 13
        raise MyException()
    else:
        out.value = 12


def raised_and_caught(out: Container) -> None:
    Requires(Acc(out.value))
    Ensures(Acc(out.value) and out.value == 12)
    Exsures(MyException, False)
    try:
        raise MyException()
    except MyException:
        out.value = 12


def raised_and_caught_2(out: Container) -> None:
    Requires(Acc(out.value))
    Ensures(Acc(out.value) and (out.value == 24 or out.value == 39))
    tmp = Container()
    try:
        helper(tmp, 45)
        out.value = 2 * tmp.value
    except MyException:
        out.value = 3 * tmp.value

def raised_and_caught_3(out: Container) -> None:
    Requires(Acc(out.value))
    #:: ExpectedOutput(postcondition.violated:assertion.false)
    Ensures(Acc(out.value) and out.value == 13)
    Exsures(MyException, False)
    try:
        raise MyException()
    except MyException:
        out.value = 12


def raised_and_caught_4(out: Container) -> None:
    Requires(Acc(out.value))
    #:: ExpectedOutput(postcondition.violated:assertion.false)
    Ensures(Acc(out.value) and out.value == 39)
    tmp = Container()
    try:
        helper(tmp, 45)
        out.value = 2 * tmp.value
    except MyException:
        out.value = 3 * tmp.value

def nested(out: Container) -> None:
    Requires(Acc(out.value))
    Ensures(Acc(out.value) and out.value == 1 )
    try:

        try:
            raise MyException()
            Assert(False)
        except MyException:
            out.value = 33
        except Exception:
            Assert(False)
        if out.value == 33:
            raise MyOtherException()
            Assert(False)
        else:
            Assert(False)
        Assert(False)
    except MyOtherException:
        out.value = -1
    out.value *= out.value

def nested_2(out: Container) -> None:
    Requires(Acc(out.value))
    Ensures(Acc(out.value) and out.value == 1 )
    try:

        try:
            raise MyException()
            out.value = 33
        except MyException:
            out.value = 34
        except Exception:
            Assert(False)
        if out.value == 33:
            raise MyOtherException()
            Assert(False)
        else:
            #:: ExpectedOutput(assert.failed:assertion.false)
            Assert(False)
        Assert(False)
    except MyOtherException:
        out.value = -1
    out.value *= out.value


def nested_else_finally(out: Container) -> None:
    Requires(Acc(out.value))
    Ensures(Acc(out.value) and out.value == 1 )
    try:

        try:
            raise MyException()
            Assert(False)
        except MyException as e:
            out.value = 33
        except Exception:
            Assert(False)
        else:
            Assert(False)
        finally:
            out.value += 1
        if out.value == 34:
            raise MyOtherException()
            Assert(False)
        else:
            Assert(False)
        Assert(False)
    except MyOtherException:
        out.value = -1
    out.value *= out.value


def nested_else_finally_2(out: Container) -> None:
    Requires(Acc(out.value))
    Ensures(Acc(out.value) and out.value == 1 )
    try:

        try:
            raise MyException()
            Assert(False)
        except MyException as e:
            out.value = 33
        except Exception:
            Assert(False)
        else:
            Assert(False)
        finally:
            out.value += 1
        if out.value == 33:
            raise MyOtherException()
            Assert(False)
        else:
            #:: ExpectedOutput(assert.failed:assertion.false)
            Assert(False)
        Assert(False)
    except MyOtherException:
        out.value = -1
    out.value *= out.value


def nested_try_finally(out: Container) -> None:
    Requires(Acc(out.value))
    Ensures(Acc(out.value) and out.value == 1 )
    try:

        try:
            try:
                raise MyException()
            finally:
                out.value = 30
            Assert(False)
        except MyException as e:
            out.value = out.value + 3
        except Exception:
            Assert(False)
        else:
            Assert(False)
        finally:
            out.value += 1
        if out.value == 34:
            raise MyOtherException()
            Assert(False)
        else:
            Assert(False)
        Assert(False)
    except MyOtherException:
        out.value = -1
    out.value *= out.value

def nested_try_finally_2(out: Container) -> None:
    Requires(Acc(out.value))
    Ensures(Acc(out.value) and out.value == 1 )
    try:

        try:
            try:
                raise MyException()
            finally:
                out.value = 30
            Assert(False)
        except MyException as e:
            out.value = out.value + 3
        except Exception:
            Assert(False)
        else:
            Assert(False)
        finally:
            out.value += 1
        if out.value == 33:
            raise MyOtherException()
            Assert(False)
        else:
            #:: ExpectedOutput(assert.failed:assertion.false)
            Assert(False)
        Assert(False)
    except MyOtherException:
        out.value = -1
    out.value *= out.value


def return_finally(out: Container) -> int:
    Requires(Acc(out.value))
    Ensures(Acc(out.value) and out.value == 5)
    Ensures(Result() == 15)
    out.value = 1
    try:
        try:
            return 15
        finally:
            out.value = out.value * 3
    except MyException:
        out.value = out.value + 1000
    finally:
        out.value = out.value + 2

def return_finally_2(out: Container) -> int:
    Requires(Acc(out.value))
    #:: ExpectedOutput(postcondition.violated:assertion.false)
    Ensures(Acc(out.value) and out.value == 1)
    Ensures(Result() == 15)
    out.value = 1
    try:
        try:
            return 15
        finally:
            out.value = out.value * 3
    except MyException:
        out.value = out.value + 1000
    finally:
        out.value = out.value + 2

def double_return_finally(out: Container) -> int:
    Requires(Acc(out.value))
    Ensures(Acc(out.value) and out.value == 3)
    Ensures(Result() == 5)
    out.value = 1
    try:
        try:
            return 15
        finally:
            out.value = out.value * 3
    except MyException:
        out.value = out.value + 1000
    finally:
        return out.value + 2

def double_return_finally_2(out: Container) -> int:
    Requires(Acc(out.value))
    Ensures(Acc(out.value) and out.value == 3)
    #:: ExpectedOutput(postcondition.violated:assertion.false)
    Ensures(Result() == 15)
    out.value = 1
    try:
        try:
            return 15
        finally:
            out.value = out.value * 3
    except MyException:
        out.value = out.value + 1000
    finally:
        return out.value + 2

def exception_use(out: Container) -> None:
    Requires(Acc(out.value))
    Ensures(Acc(out.value) and out.value == 104)
    try:
        raise ParameterizedException(52)
        Assert(False)
    except MyException as e:
        Assert(False)
    except ParameterizedException as e2:
        out.value = e2.num
    finally:
        out.value *= 2

def exception_use_2(out: Container, inp: bool) -> None:
    Requires(Acc(out.value))
    Ensures(Acc(out.value))
    Ensures(Implies(not inp, out.value == 72))
    Ensures(Implies(inp, out.value == 74))
    try:
        if inp:
            out.value = 14
            raise ParameterizedException(23)
        else:
            raise MyException()
        Assert(False)
    except MyException as e:
        out.value = 36
    except ParameterizedException as e2:
        out.value += e2.num
    finally:
        out.value *= 2

def exception_use_3(out: Container, inp: bool) -> None:
    Requires(Acc(out.value))
    Ensures(Acc(out.value))
    Ensures(Implies(not inp, out.value == 72))
    #:: ExpectedOutput(postcondition.violated:assertion.false)
    Ensures(Implies(inp, out.value == 74))
    try:
        if inp:
            out.value = 14
            raise ParameterizedException(45)
        else:
            raise MyException()
        Assert(False)
    except MyException as e:
        out.value = 36
    except ParameterizedException as e2:
        out.value += e2.num
    finally:
        out.value *= 2