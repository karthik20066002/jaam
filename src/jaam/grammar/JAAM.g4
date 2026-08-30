grammar JAAM;

program       : statement* EOF ;
statement     : defaultBlock | primitiveDecl | directive ;
defaultBlock  : DEFAULT IDENT? LBRACE (IDENT COLON expr SEMI)* RBRACE ;
primitiveDecl : IDENT IDENT LPAREN args? RPAREN SEMI ;
directive     : IDENT expr SEMI ;
args          : arg (COMMA arg)* ;
arg           : (IDENT COLON)? expr ;
expr          : call | NUMBER | IDENT | tuple ;
tuple         : LPAREN expr COMMA expr (COMMA expr)? RPAREN ;
call          : IDENT LPAREN args? RPAREN ;

DEFAULT : 'default' ;
LBRACE  : '{' ;
RBRACE  : '}' ;
LPAREN  : '(' ;
RPAREN  : ')' ;
COLON   : ':' ;
COMMA   : ',' ;
SEMI    : ';' ;

NUMBER
  : ('+' | '-')? (DIGIT+ ('.' DIGIT*)? | '.' DIGIT+) ([eE] ('+' | '-')? DIGIT+)?
    [a-zA-Z]*
  ;
IDENT : [a-zA-Z_] [a-zA-Z_0-9]* ;

LINE_COMMENT  : '//' ~[\r\n]* -> skip ;
BLOCK_COMMENT : '/*' .*? '*/' -> skip ;
WS            : [ \t\r\n]+ -> skip ;
ERROR_CHAR    : . ;

fragment DIGIT : [0-9] ;

