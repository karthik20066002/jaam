# Generated from JAAM.g4 by ANTLR 4.13.2
# encoding: utf-8
from antlr4 import *
from io import StringIO
import sys
if sys.version_info[1] > 5:
	from typing import TextIO
else:
	from typing.io import TextIO

def serializedATN():
    return [
        4,1,14,101,2,0,7,0,2,1,7,1,2,2,7,2,2,3,7,3,2,4,7,4,2,5,7,5,2,6,7,
        6,2,7,7,7,2,8,7,8,2,9,7,9,1,0,5,0,22,8,0,10,0,12,0,25,9,0,1,0,1,
        0,1,1,1,1,1,1,3,1,32,8,1,1,2,1,2,3,2,36,8,2,1,2,1,2,1,2,1,2,1,2,
        1,2,5,2,44,8,2,10,2,12,2,47,9,2,1,2,1,2,1,3,1,3,1,3,1,3,3,3,55,8,
        3,1,3,1,3,1,3,1,4,1,4,1,4,1,4,1,5,1,5,1,5,5,5,67,8,5,10,5,12,5,70,
        9,5,1,6,1,6,3,6,74,8,6,1,6,1,6,1,7,1,7,1,7,1,7,3,7,82,8,7,1,8,1,
        8,1,8,1,8,1,8,1,8,3,8,90,8,8,1,8,1,8,1,9,1,9,1,9,3,9,97,8,9,1,9,
        1,9,1,9,0,0,10,0,2,4,6,8,10,12,14,16,18,0,0,103,0,23,1,0,0,0,2,31,
        1,0,0,0,4,33,1,0,0,0,6,50,1,0,0,0,8,59,1,0,0,0,10,63,1,0,0,0,12,
        73,1,0,0,0,14,81,1,0,0,0,16,83,1,0,0,0,18,93,1,0,0,0,20,22,3,2,1,
        0,21,20,1,0,0,0,22,25,1,0,0,0,23,21,1,0,0,0,23,24,1,0,0,0,24,26,
        1,0,0,0,25,23,1,0,0,0,26,27,5,0,0,1,27,1,1,0,0,0,28,32,3,4,2,0,29,
        32,3,6,3,0,30,32,3,8,4,0,31,28,1,0,0,0,31,29,1,0,0,0,31,30,1,0,0,
        0,32,3,1,0,0,0,33,35,5,1,0,0,34,36,5,10,0,0,35,34,1,0,0,0,35,36,
        1,0,0,0,36,37,1,0,0,0,37,45,5,2,0,0,38,39,5,10,0,0,39,40,5,6,0,0,
        40,41,3,14,7,0,41,42,5,8,0,0,42,44,1,0,0,0,43,38,1,0,0,0,44,47,1,
        0,0,0,45,43,1,0,0,0,45,46,1,0,0,0,46,48,1,0,0,0,47,45,1,0,0,0,48,
        49,5,3,0,0,49,5,1,0,0,0,50,51,5,10,0,0,51,52,5,10,0,0,52,54,5,4,
        0,0,53,55,3,10,5,0,54,53,1,0,0,0,54,55,1,0,0,0,55,56,1,0,0,0,56,
        57,5,5,0,0,57,58,5,8,0,0,58,7,1,0,0,0,59,60,5,10,0,0,60,61,3,14,
        7,0,61,62,5,8,0,0,62,9,1,0,0,0,63,68,3,12,6,0,64,65,5,7,0,0,65,67,
        3,12,6,0,66,64,1,0,0,0,67,70,1,0,0,0,68,66,1,0,0,0,68,69,1,0,0,0,
        69,11,1,0,0,0,70,68,1,0,0,0,71,72,5,10,0,0,72,74,5,6,0,0,73,71,1,
        0,0,0,73,74,1,0,0,0,74,75,1,0,0,0,75,76,3,14,7,0,76,13,1,0,0,0,77,
        82,3,18,9,0,78,82,5,9,0,0,79,82,5,10,0,0,80,82,3,16,8,0,81,77,1,
        0,0,0,81,78,1,0,0,0,81,79,1,0,0,0,81,80,1,0,0,0,82,15,1,0,0,0,83,
        84,5,4,0,0,84,85,3,14,7,0,85,86,5,7,0,0,86,89,3,14,7,0,87,88,5,7,
        0,0,88,90,3,14,7,0,89,87,1,0,0,0,89,90,1,0,0,0,90,91,1,0,0,0,91,
        92,5,5,0,0,92,17,1,0,0,0,93,94,5,10,0,0,94,96,5,4,0,0,95,97,3,10,
        5,0,96,95,1,0,0,0,96,97,1,0,0,0,97,98,1,0,0,0,98,99,5,5,0,0,99,19,
        1,0,0,0,10,23,31,35,45,54,68,73,81,89,96
    ]

class JAAMParser ( Parser ):

    grammarFileName = "JAAM.g4"

    atn = ATNDeserializer().deserialize(serializedATN())

    decisionsToDFA = [ DFA(ds, i) for i, ds in enumerate(atn.decisionToState) ]

    sharedContextCache = PredictionContextCache()

    literalNames = [ "<INVALID>", "'default'", "'{'", "'}'", "'('", "')'", 
                     "':'", "','", "';'" ]

    symbolicNames = [ "<INVALID>", "DEFAULT", "LBRACE", "RBRACE", "LPAREN", 
                      "RPAREN", "COLON", "COMMA", "SEMI", "NUMBER", "IDENT", 
                      "LINE_COMMENT", "BLOCK_COMMENT", "WS", "ERROR_CHAR" ]

    RULE_program = 0
    RULE_statement = 1
    RULE_defaultBlock = 2
    RULE_primitiveDecl = 3
    RULE_directive = 4
    RULE_args = 5
    RULE_arg = 6
    RULE_expr = 7
    RULE_tuple = 8
    RULE_call = 9

    ruleNames =  [ "program", "statement", "defaultBlock", "primitiveDecl", 
                   "directive", "args", "arg", "expr", "tuple", "call" ]

    EOF = Token.EOF
    DEFAULT=1
    LBRACE=2
    RBRACE=3
    LPAREN=4
    RPAREN=5
    COLON=6
    COMMA=7
    SEMI=8
    NUMBER=9
    IDENT=10
    LINE_COMMENT=11
    BLOCK_COMMENT=12
    WS=13
    ERROR_CHAR=14

    def __init__(self, input:TokenStream, output:TextIO = sys.stdout):
        super().__init__(input, output)
        self.checkVersion("4.13.2")
        self._interp = ParserATNSimulator(self, self.atn, self.decisionsToDFA, self.sharedContextCache)
        self._predicates = None




    class ProgramContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def EOF(self):
            return self.getToken(JAAMParser.EOF, 0)

        def statement(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(JAAMParser.StatementContext)
            else:
                return self.getTypedRuleContext(JAAMParser.StatementContext,i)


        def getRuleIndex(self):
            return JAAMParser.RULE_program

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitProgram" ):
                return visitor.visitProgram(self)
            else:
                return visitor.visitChildren(self)




    def program(self):

        localctx = JAAMParser.ProgramContext(self, self._ctx, self.state)
        self.enterRule(localctx, 0, self.RULE_program)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 23
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while _la==1 or _la==10:
                self.state = 20
                self.statement()
                self.state = 25
                self._errHandler.sync(self)
                _la = self._input.LA(1)

            self.state = 26
            self.match(JAAMParser.EOF)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class StatementContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def defaultBlock(self):
            return self.getTypedRuleContext(JAAMParser.DefaultBlockContext,0)


        def primitiveDecl(self):
            return self.getTypedRuleContext(JAAMParser.PrimitiveDeclContext,0)


        def directive(self):
            return self.getTypedRuleContext(JAAMParser.DirectiveContext,0)


        def getRuleIndex(self):
            return JAAMParser.RULE_statement

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitStatement" ):
                return visitor.visitStatement(self)
            else:
                return visitor.visitChildren(self)




    def statement(self):

        localctx = JAAMParser.StatementContext(self, self._ctx, self.state)
        self.enterRule(localctx, 2, self.RULE_statement)
        try:
            self.state = 31
            self._errHandler.sync(self)
            la_ = self._interp.adaptivePredict(self._input,1,self._ctx)
            if la_ == 1:
                self.enterOuterAlt(localctx, 1)
                self.state = 28
                self.defaultBlock()
                pass

            elif la_ == 2:
                self.enterOuterAlt(localctx, 2)
                self.state = 29
                self.primitiveDecl()
                pass

            elif la_ == 3:
                self.enterOuterAlt(localctx, 3)
                self.state = 30
                self.directive()
                pass


        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class DefaultBlockContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def DEFAULT(self):
            return self.getToken(JAAMParser.DEFAULT, 0)

        def LBRACE(self):
            return self.getToken(JAAMParser.LBRACE, 0)

        def RBRACE(self):
            return self.getToken(JAAMParser.RBRACE, 0)

        def IDENT(self, i:int=None):
            if i is None:
                return self.getTokens(JAAMParser.IDENT)
            else:
                return self.getToken(JAAMParser.IDENT, i)

        def COLON(self, i:int=None):
            if i is None:
                return self.getTokens(JAAMParser.COLON)
            else:
                return self.getToken(JAAMParser.COLON, i)

        def expr(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(JAAMParser.ExprContext)
            else:
                return self.getTypedRuleContext(JAAMParser.ExprContext,i)


        def SEMI(self, i:int=None):
            if i is None:
                return self.getTokens(JAAMParser.SEMI)
            else:
                return self.getToken(JAAMParser.SEMI, i)

        def getRuleIndex(self):
            return JAAMParser.RULE_defaultBlock

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitDefaultBlock" ):
                return visitor.visitDefaultBlock(self)
            else:
                return visitor.visitChildren(self)




    def defaultBlock(self):

        localctx = JAAMParser.DefaultBlockContext(self, self._ctx, self.state)
        self.enterRule(localctx, 4, self.RULE_defaultBlock)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 33
            self.match(JAAMParser.DEFAULT)
            self.state = 35
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            if _la==10:
                self.state = 34
                self.match(JAAMParser.IDENT)


            self.state = 37
            self.match(JAAMParser.LBRACE)
            self.state = 45
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while _la==10:
                self.state = 38
                self.match(JAAMParser.IDENT)
                self.state = 39
                self.match(JAAMParser.COLON)
                self.state = 40
                self.expr()
                self.state = 41
                self.match(JAAMParser.SEMI)
                self.state = 47
                self._errHandler.sync(self)
                _la = self._input.LA(1)

            self.state = 48
            self.match(JAAMParser.RBRACE)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class PrimitiveDeclContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def IDENT(self, i:int=None):
            if i is None:
                return self.getTokens(JAAMParser.IDENT)
            else:
                return self.getToken(JAAMParser.IDENT, i)

        def LPAREN(self):
            return self.getToken(JAAMParser.LPAREN, 0)

        def RPAREN(self):
            return self.getToken(JAAMParser.RPAREN, 0)

        def SEMI(self):
            return self.getToken(JAAMParser.SEMI, 0)

        def args(self):
            return self.getTypedRuleContext(JAAMParser.ArgsContext,0)


        def getRuleIndex(self):
            return JAAMParser.RULE_primitiveDecl

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitPrimitiveDecl" ):
                return visitor.visitPrimitiveDecl(self)
            else:
                return visitor.visitChildren(self)




    def primitiveDecl(self):

        localctx = JAAMParser.PrimitiveDeclContext(self, self._ctx, self.state)
        self.enterRule(localctx, 6, self.RULE_primitiveDecl)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 50
            self.match(JAAMParser.IDENT)
            self.state = 51
            self.match(JAAMParser.IDENT)
            self.state = 52
            self.match(JAAMParser.LPAREN)
            self.state = 54
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            if (((_la) & ~0x3f) == 0 and ((1 << _la) & 1552) != 0):
                self.state = 53
                self.args()


            self.state = 56
            self.match(JAAMParser.RPAREN)
            self.state = 57
            self.match(JAAMParser.SEMI)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class DirectiveContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def IDENT(self):
            return self.getToken(JAAMParser.IDENT, 0)

        def expr(self):
            return self.getTypedRuleContext(JAAMParser.ExprContext,0)


        def SEMI(self):
            return self.getToken(JAAMParser.SEMI, 0)

        def getRuleIndex(self):
            return JAAMParser.RULE_directive

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitDirective" ):
                return visitor.visitDirective(self)
            else:
                return visitor.visitChildren(self)




    def directive(self):

        localctx = JAAMParser.DirectiveContext(self, self._ctx, self.state)
        self.enterRule(localctx, 8, self.RULE_directive)
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 59
            self.match(JAAMParser.IDENT)
            self.state = 60
            self.expr()
            self.state = 61
            self.match(JAAMParser.SEMI)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class ArgsContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def arg(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(JAAMParser.ArgContext)
            else:
                return self.getTypedRuleContext(JAAMParser.ArgContext,i)


        def COMMA(self, i:int=None):
            if i is None:
                return self.getTokens(JAAMParser.COMMA)
            else:
                return self.getToken(JAAMParser.COMMA, i)

        def getRuleIndex(self):
            return JAAMParser.RULE_args

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitArgs" ):
                return visitor.visitArgs(self)
            else:
                return visitor.visitChildren(self)




    def args(self):

        localctx = JAAMParser.ArgsContext(self, self._ctx, self.state)
        self.enterRule(localctx, 10, self.RULE_args)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 63
            self.arg()
            self.state = 68
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while _la==7:
                self.state = 64
                self.match(JAAMParser.COMMA)
                self.state = 65
                self.arg()
                self.state = 70
                self._errHandler.sync(self)
                _la = self._input.LA(1)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class ArgContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def expr(self):
            return self.getTypedRuleContext(JAAMParser.ExprContext,0)


        def IDENT(self):
            return self.getToken(JAAMParser.IDENT, 0)

        def COLON(self):
            return self.getToken(JAAMParser.COLON, 0)

        def getRuleIndex(self):
            return JAAMParser.RULE_arg

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitArg" ):
                return visitor.visitArg(self)
            else:
                return visitor.visitChildren(self)




    def arg(self):

        localctx = JAAMParser.ArgContext(self, self._ctx, self.state)
        self.enterRule(localctx, 12, self.RULE_arg)
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 73
            self._errHandler.sync(self)
            la_ = self._interp.adaptivePredict(self._input,6,self._ctx)
            if la_ == 1:
                self.state = 71
                self.match(JAAMParser.IDENT)
                self.state = 72
                self.match(JAAMParser.COLON)


            self.state = 75
            self.expr()
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class ExprContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def call(self):
            return self.getTypedRuleContext(JAAMParser.CallContext,0)


        def NUMBER(self):
            return self.getToken(JAAMParser.NUMBER, 0)

        def IDENT(self):
            return self.getToken(JAAMParser.IDENT, 0)

        def tuple_(self):
            return self.getTypedRuleContext(JAAMParser.TupleContext,0)


        def getRuleIndex(self):
            return JAAMParser.RULE_expr

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitExpr" ):
                return visitor.visitExpr(self)
            else:
                return visitor.visitChildren(self)




    def expr(self):

        localctx = JAAMParser.ExprContext(self, self._ctx, self.state)
        self.enterRule(localctx, 14, self.RULE_expr)
        try:
            self.state = 81
            self._errHandler.sync(self)
            la_ = self._interp.adaptivePredict(self._input,7,self._ctx)
            if la_ == 1:
                self.enterOuterAlt(localctx, 1)
                self.state = 77
                self.call()
                pass

            elif la_ == 2:
                self.enterOuterAlt(localctx, 2)
                self.state = 78
                self.match(JAAMParser.NUMBER)
                pass

            elif la_ == 3:
                self.enterOuterAlt(localctx, 3)
                self.state = 79
                self.match(JAAMParser.IDENT)
                pass

            elif la_ == 4:
                self.enterOuterAlt(localctx, 4)
                self.state = 80
                self.tuple_()
                pass


        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class TupleContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def LPAREN(self):
            return self.getToken(JAAMParser.LPAREN, 0)

        def expr(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(JAAMParser.ExprContext)
            else:
                return self.getTypedRuleContext(JAAMParser.ExprContext,i)


        def COMMA(self, i:int=None):
            if i is None:
                return self.getTokens(JAAMParser.COMMA)
            else:
                return self.getToken(JAAMParser.COMMA, i)

        def RPAREN(self):
            return self.getToken(JAAMParser.RPAREN, 0)

        def getRuleIndex(self):
            return JAAMParser.RULE_tuple

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitTuple" ):
                return visitor.visitTuple(self)
            else:
                return visitor.visitChildren(self)




    def tuple_(self):

        localctx = JAAMParser.TupleContext(self, self._ctx, self.state)
        self.enterRule(localctx, 16, self.RULE_tuple)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 83
            self.match(JAAMParser.LPAREN)
            self.state = 84
            self.expr()
            self.state = 85
            self.match(JAAMParser.COMMA)
            self.state = 86
            self.expr()
            self.state = 89
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            if _la==7:
                self.state = 87
                self.match(JAAMParser.COMMA)
                self.state = 88
                self.expr()


            self.state = 91
            self.match(JAAMParser.RPAREN)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class CallContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def IDENT(self):
            return self.getToken(JAAMParser.IDENT, 0)

        def LPAREN(self):
            return self.getToken(JAAMParser.LPAREN, 0)

        def RPAREN(self):
            return self.getToken(JAAMParser.RPAREN, 0)

        def args(self):
            return self.getTypedRuleContext(JAAMParser.ArgsContext,0)


        def getRuleIndex(self):
            return JAAMParser.RULE_call

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitCall" ):
                return visitor.visitCall(self)
            else:
                return visitor.visitChildren(self)




    def call(self):

        localctx = JAAMParser.CallContext(self, self._ctx, self.state)
        self.enterRule(localctx, 18, self.RULE_call)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 93
            self.match(JAAMParser.IDENT)
            self.state = 94
            self.match(JAAMParser.LPAREN)
            self.state = 96
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            if (((_la) & ~0x3f) == 0 and ((1 << _la) & 1552) != 0):
                self.state = 95
                self.args()


            self.state = 98
            self.match(JAAMParser.RPAREN)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx





