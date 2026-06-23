import sys
from . import console

def main():
    from .cli import SamCodeCLI
    try:
        agent = SamCodeCLI()
        agent.run()
    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/red]")
        sys.exit(1)

if __name__ == "__main__":
    main()