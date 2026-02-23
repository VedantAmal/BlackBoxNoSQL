from flask import Flask, render_template_string, request
import os

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Python Challenge</title>
    <style>
        body { font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px; }
        .container { background: #f9f9f9; padding: 30px; border-radius: 8px; }
        input { padding: 10px; width: 300px; margin: 10px 0; }
        button { padding: 10px 20px; background: #007bff; color: white; border: none; cursor: pointer; }
        .result { margin-top: 20px; padding: 15px; background: #e7f3ff; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🐍 Python Challenge - Command Executor</h1>
        <p>This application executes Python commands. Can you read the flag?</p>
        
        <form method="POST">
            <input type="text" name="cmd" placeholder="Enter Python expression (e.g., 1+1)" />
            <button type="submit">Execute</button>
        </form>
        
        {% if result %}
        <div class="result">
            <strong>Result:</strong> {{ result }}
        </div>
        {% endif %}
        
        <p><small>Hint: The flag is in /flag.txt</small></p>
    </div>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    result = None
    if request.method == 'POST':
        cmd = request.form.get('cmd', '')
        try:
            # Vulnerable to command injection!
            # Solution: open('/flag.txt').read()
            result = eval(cmd)
        except Exception as e:
            result = f"Error: {str(e)}"
    
    return render_template_string(HTML, result=result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=False)
