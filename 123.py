from flask import Flask, render_template, request, redirect, url_for, abort
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

# Initialize Flask app and configure database URI
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///rummy.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy with Flask app
db = SQLAlchemy(app)

# Define models for Users and Scores
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)

class Score(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    round = db.Column(db.Integer, nullable=False)
    score = db.Column(db.Integer, nullable=False)          # adjusted score
    normal_score = db.Column(db.Integer, nullable=False)   # raw input score
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('scores', lazy=True))


# Create database tables if they don't exist
def create_tables():
    if not os.path.exists('rummy.db'):
        with app.app_context():
            db.create_all()

# Ensure that tables are created before the app starts handling requests
create_tables()

# Route for registering players
@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        usernames_raw = request.form.get('usernames', '')
        usernames = [name.strip().upper() for name in usernames_raw.split(',') if name.strip()]
        if not usernames:
            error = "Please enter at least one username."
            return render_template('register.html', title="Register Players", error=error)
        # Add users if not exist
        for name in usernames:
            if not User.query.filter_by(username=name).first():
                db.session.add(User(username=name))
        db.session.commit()
        return redirect(url_for('leaderboard'))
    return render_template('register.html', title="Register Players", error=error)

# Route for adding scores for players
@app.route('/add', methods=['GET', 'POST'])
def add_score():
    players = User.query.order_by(User.username).all()
    error = None
    if not players:
        return redirect(url_for('register'))

    if request.method == 'POST':
        latest_round = db.session.query(db.func.max(Score.round)).scalar()
        round_number = 1 if latest_round is None else latest_round + 1
        
        normal_scores = {}
        for player in players:
            try:
                val = request.form[f'score_{player.username}']
                score_val = int(val)
                if score_val < 0:
                    error = "Scores must be zero or positive integers."
                    return render_template('add_score.html', title="Add Score", players=players, error=error)
                normal_scores[player.id] = score_val
            except (ValueError, KeyError):
                error = "Invalid input detected. Please enter valid scores."
                return render_template('add_score.html', title="Add Score", players=players, error=error)
        
        # Validate exactly one zero (winner)
        zero_scores = [uid for uid, score in normal_scores.items() if score == 0]
        if len(zero_scores) != 1:
            error = "Exactly one player must have score zero (the winner)."
            return render_template('add_score.html', title="Add Score", players=players, error=error)

        winner_id = zero_scores[0]

        # Calculate adjusted scores
        round_scores = {}
        total_others = sum(score for uid, score in normal_scores.items() if uid != winner_id)
        for uid, score_val in normal_scores.items():
            if uid == winner_id:
                round_scores[uid] = total_others  # winner gets sum of others
            else:
                round_scores[uid] = -score_val    # losers get negative scores

        # Save scores to DB
        for player in players:
            scr = Score(user_id=player.id, round=round_number,
                        score=round_scores[player.id], normal_score=normal_scores[player.id])
            db.session.add(scr)
        db.session.commit()
        return redirect(url_for('leaderboard'))

    return render_template('add_score.html', title="Add Score", players=players, error=error)

# Route for displaying the leaderboard
@app.route('/')
def leaderboard():
    # Base query for total scores
    results = db.session.query(
        User.id,
        User.username,
        db.func.coalesce(db.func.sum(Score.score), 0).label('adjusted_total'),
        db.func.coalesce(db.func.sum(Score.normal_score), 0).label('normal_total')
    ).outerjoin(Score).group_by(User.id).order_by(db.func.sum(Score.score).desc()).all()

    leaderboard_data = []
    for user_id, username, adjusted_total, normal_total in results:
        # Count of 20s
        num_20s = db.session.query(db.func.count()).filter(
            Score.user_id == user_id,
            Score.normal_score == 20
        ).scalar()

        # Count of wins (normal_score == 0)
        num_wins = db.session.query(db.func.count()).filter(
            Score.user_id == user_id,
            Score.normal_score == 0
        ).scalar()

        # Count of scores between 70 and 80
        in_range_70_80 = db.session.query(db.func.count()).filter(
            Score.user_id == user_id,
            Score.normal_score.between(70, 80)
        ).scalar()

        leaderboard_data.append({
            'username': username,
            'adjusted_total': adjusted_total,
            'normal_total': normal_total,
            'num_20s': num_20s,
            'num_wins': num_wins,
            'in_range_70_80': in_range_70_80
        })

    return render_template('leaderboard.html', title="Leaderboard", scores=leaderboard_data)

# Route for displaying history of all scores with editing links
@app.route('/history')
def history():
    players = User.query.order_by(User.username).all()
    player_names = [p.username for p in players]

    # Get scores joined with users, ordered by round and username
    scores = db.session.query(Score, User).join(User).order_by(Score.round, User.username).all()

    rounds_dict = {}
    # Map rounds: round_num -> { username: score_obj }
    for score_obj, user_obj in scores:
        rounds_dict.setdefault(score_obj.round, {})[user_obj.username] = score_obj

    rounds_list = []
    for rnd in sorted(rounds_dict.keys()):
        scores_in_round = rounds_dict[rnd]
        # Prepare list with Score objects or None if missing
        round_scores = []
        for pname in player_names:
            round_scores.append(scores_in_round.get(pname))
        rounds_list.append({'round': rnd, 'scores': round_scores})

    return render_template('history.html', title="Score History", players=player_names, history=rounds_list)

# Route to edit a single score entry
@app.route('/edit_score/<int:score_id>', methods=['GET', 'POST'])
def edit_score(score_id):
    score = Score.query.get_or_404(score_id)
    player = User.query.get(score.user_id)
    error = None

    if request.method == 'POST':
        try:
            new_normal_score = int(request.form.get('normal_score', '').strip())
            if new_normal_score < 0:
                error = "Score must be zero or positive."
                return render_template('edit_score.html', score=score, player=player, error=error)

            # Fetch all scores for this round to recalc winner score after edit
            scores = Score.query.filter_by(round=score.round).all()
            
            # Temporarily update this score's normal_score for calculation
            old_normal = score.normal_score
            score.normal_score = new_normal_score
            db.session.flush()  # update before calculating

            zero_scores = [s for s in scores if s.normal_score == 0]

            if len(zero_scores) != 1:
                error = "Exactly one player must have zero score (winner) for the round."
                score.normal_score = old_normal  # rollback change
                db.session.flush()
                return render_template('edit_score.html', score=score, player=player, error=error)

            winner = zero_scores[0]
            other_sum = sum(s.normal_score for s in scores if s.id != winner.id)

            for s in scores:
                if s.id == winner.id:
                    s.score = other_sum
                else:
                    s.score = -s.normal_score

            db.session.commit()
            return redirect(url_for('history'))

        except ValueError:
            error = "Please enter a valid integer."
            return render_template('edit_score.html', score=score, player=player, error=error)

    return render_template('edit_score.html', score=score, player=player, error=error)

# Route for resetting all data
@app.route('/reset', methods=['POST'])
def reset():
    db.session.query(Score).delete()
    db.session.query(User).delete()
    db.session.commit()
    return redirect(url_for('leaderboard'))

if __name__ == '__main__':
    app.run(debug=True)
