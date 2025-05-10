from flask import Flask, render_template, request, redirect, url_for
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
    score = db.Column(db.Integer, nullable=False)
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
    if request.method == 'POST':
        usernames = request.form['usernames'].split(',')
        for name in map(str.strip, usernames):
            if name and not User.query.filter_by(username=name).first():
                db.session.add(User(username=name))
        db.session.commit()
        return redirect(url_for('leaderboard'))
    return render_template('register.html', title="Register Players")

# Route for adding scores for players
@app.route('/add', methods=['GET', 'POST'])
def add_score():
    players = User.query.all()
    if request.method == 'POST':
        # Get the latest round number; if none exists, start with 1
        latest_round = db.session.query(db.func.max(Score.round)).scalar()
        round_number = 1 if latest_round is None else latest_round + 1
        
        # Collect all scores first
        round_scores = {}
        for player in players:
            score_val = int(request.form[f'score_{player.username}'])
            # Store original input for non-zero scores
            if score_val > 0:
                round_scores[player.id] = -score_val
            elif score_val < 0:
                round_scores[player.id] = abs(score_val)
            else:
                round_scores[player.id] = 0

        # Process scores and handle zero cases
        for player in players:
            score_val = round_scores[player.id]
            
            if score_val == 0:
                # Sum other players' scores for this round
                other_scores_sum = sum(
                    s for pid, s in round_scores.items()
                    if pid != player.id and s != 0
                )
                score_val = abs(other_scores_sum)  # Ensure positive
                
            score = Score(user_id=player.id, round=round_number, score=score_val)
            db.session.add(score)
        
        db.session.commit()
        return redirect(url_for('leaderboard'))
    
    return render_template('add_score.html', title="Add Score", players=[p.username for p in players])

# Route for displaying the leaderboard
@app.route('/')
def leaderboard():
    scores = db.session.query(
        User.username,
        db.func.sum(Score.score).label('total_score')
    ).join(Score).group_by(User.id).order_by(db.func.sum(Score.score).desc()).all()
    return render_template('leaderboard.html', title="Leaderboard", scores=scores)

# Route for displaying history of all scores
@app.route('/history')
def history():
    # Get all players
    players = User.query.all()
    player_names = [p.username for p in players]
    
    # Get all scores and group by round
    scores = db.session.query(Score, User).join(User).order_by(Score.round).all()
    
    # Create a dictionary to store scores by round
    rounds = {}
    for score, user in scores:
        if score.round not in rounds:
            rounds[score.round] = {}
        rounds[score.round][user.username] = score.score
    
    # Prepare data for template: list of rounds with scores for each player
    history_data = [
        {'round': round_num, 'scores': [rounds[round_num].get(p, 0) for p in player_names]}
        for round_num in sorted(rounds.keys())
    ]
    
    return render_template('history.html', title="History", players=player_names, history=history_data)

# Route for resetting the leaderboard and scores
@app.route('/reset', methods=['POST'])
def reset():
    db.session.query(Score).delete()
    db.session.query(User).delete()
    db.session.commit()
    return redirect(url_for('leaderboard'))

# Run the Flask app
if __name__ == '__main__':
    app.run(debug=True)