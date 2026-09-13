# CONTRACT: beat_the_system
# Tic-tac-toe against the Arbiter, which looks exactly one move ahead: it
# takes a win, else blocks yours, else prefers centre, corners, edges,
# with random tie-breaks. It never sees a fork. Search the game tree
# against that policy and only ever play a move that forces a win against
# EVERY tie-break the Arbiter might choose. Repeat until the streak hits
# target(), then transmit the token.

transmitter = get_component("transmitter")
link = transmitter.connect("earth")
if link.status != "ok":
    print("[arbiter] transmitter:", link.message)

arb = self.contract.arbiter

LINES = [[0, 1, 2], [3, 4, 5], [6, 7, 8],
         [0, 3, 6], [1, 4, 7], [2, 5, 8],
         [0, 4, 8], [2, 4, 6]]
TIERS = [[4], [0, 2, 6, 8], [1, 3, 5, 7]]
ME = 1
ARB = 2


def winner(board):
    for line in LINES:
        a = board[line[0]]
        if a != 0 and a == board[line[1]] and a == board[line[2]]:
            return a
    return 0


def empties(board):
    out = []
    for i in range(9):
        if board[i] == 0:
            out.append(i)
    return out


def winning_cells(board, mark):
    out = []
    for i in empties(board):
        trial = list(board)
        trial[i] = mark
        if winner(trial) == mark:
            out.append(i)
    return out


def arbiter_options(board):
    # Every cell the Arbiter's policy could pick from this position.
    take = winning_cells(board, ARB)
    if len(take) > 0:
        return take
    block = winning_cells(board, ME)
    if len(block) > 0:
        return block
    for tier in TIERS:
        open_cells = []
        for i in tier:
            if board[i] == 0:
                open_cells.append(i)
        if len(open_cells) > 0:
            return open_cells
    return empties(board)


memo = {}


def forced_win(board, my_turn):
    # True if I can force a win from here whatever the Arbiter does.
    w = winner(board)
    if w == ME:
        return True
    if w == ARB or len(empties(board)) == 0:
        return False

    key = ""
    for v in board:
        key = key + str(v)
    if my_turn:
        key = key + "m"
    else:
        key = key + "a"
    if memo.has(key):
        return memo[key]

    if my_turn:
        result = False
        for i in empties(board):
            trial = list(board)
            trial[i] = ME
            if forced_win(trial, False):
                result = True
                break
    else:
        result = True
        for i in arbiter_options(board):
            trial = list(board)
            trial[i] = ARB
            if not forced_win(trial, True):
                result = False
                break

    memo[key] = result
    return result


def best_move(board):
    for i in empties(board):
        trial = list(board)
        trial[i] = ME
        if forced_win(trial, False):
            return i
    # No forced win from here (should not happen from an empty board).
    return empties(board)[0]


def read_board():
    board = []
    for cell in arb.board():
        if cell == "you":
            board.append(ME)
        elif cell == "arbiter":
            board.append(ARB)
        else:
            board.append(0)
    return board


target = arb.target()
print("[arbiter] need", target, "wins in a row")

games = 0
while arb.streak() < target:
    started = arb.new_game()
    if started.status != "ok":
        print("[arbiter] new_game:", started.message)
        sleep(1)
        continue
    games = games + 1

    while arb.result() == "ongoing":
        played = arb.play(best_move(read_board()))
        if played.status != "ok":
            print("[arbiter] play:", played.message)
            break

    outcome = arb.result()
    if outcome == "win":
        print("[arbiter] win", arb.streak(), "/", target)
    else:
        print("[arbiter]", outcome, "- streak reset (game", games, ")")

token = arb.token()
print("[arbiter] token:", token)
sent = transmitter.transmit(self.contract.id, token)
print("[arbiter]", sent.status, "-", sent.message)
