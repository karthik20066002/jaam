# Generated from JAAM.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .JAAMParser import JAAMParser
else:
    from JAAMParser import JAAMParser

# This class defines a complete generic visitor for a parse tree produced by JAAMParser.

class JAAMVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by JAAMParser#program.
    def visitProgram(self, ctx:JAAMParser.ProgramContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by JAAMParser#statement.
    def visitStatement(self, ctx:JAAMParser.StatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by JAAMParser#defaultBlock.
    def visitDefaultBlock(self, ctx:JAAMParser.DefaultBlockContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by JAAMParser#primitiveDecl.
    def visitPrimitiveDecl(self, ctx:JAAMParser.PrimitiveDeclContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by JAAMParser#directive.
    def visitDirective(self, ctx:JAAMParser.DirectiveContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by JAAMParser#args.
    def visitArgs(self, ctx:JAAMParser.ArgsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by JAAMParser#arg.
    def visitArg(self, ctx:JAAMParser.ArgContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by JAAMParser#expr.
    def visitExpr(self, ctx:JAAMParser.ExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by JAAMParser#tuple.
    def visitTuple(self, ctx:JAAMParser.TupleContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by JAAMParser#call.
    def visitCall(self, ctx:JAAMParser.CallContext):
        return self.visitChildren(ctx)



del JAAMParser