"""Run with: python -m expose_interface examples.demo:app greet World --count 2."""

from expose_interface import Interface, argument, flag, option


def select_color():
    """Perform explicit configuration only when --color is selected."""
    print("Color selected")


app = Interface("demo", description="Small programs exported from Python.")


@app.program(order=0)
@argument("name")
@option("--count", "-n", help="Number of greetings.")
@flag("--color", "-G", mtd=select_color, help="Select color before greeting.")
def greet(name: str, *, count: int = 1, color: bool = False):
    """Greet someone a chosen number of times.

    This function remains callable directly from Python.
    """
    for _ in range(count):
        print(f"Hello, {name}!")


@app.program(name=None)
def welcome():
    """Run demo greet NAME to greet someone."""
    print("Run demo greet NAME to greet someone.")


main = app.main

if __name__ == "__main__":
    main()
