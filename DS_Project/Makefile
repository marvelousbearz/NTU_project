CXX ?= c++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Wpedantic
TARGET := flight_server
SOURCE := src/server.cpp

.PHONY: all test clean

all: $(TARGET)

$(TARGET): $(SOURCE)
	$(CXX) $(CXXFLAGS) $(SOURCE) -o $(TARGET)

test: $(TARGET)
	python3 -m unittest discover -s tests -v

clean:
	$(RM) $(TARGET)
